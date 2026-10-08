"""A model server instead of an agent: the page runs the agent loop itself.

An agent is a model plus a loop (show the model the tools, run the one it asks for, hand back the result, repeat).
Products such as coding agents bundle both; a model server such as Ollama is only the model. This module is the
loop, so any server that can call tools works without an agent product. Only ster's read-only tools are offered.

    * Ollama's own API (/api/chat) is used when the server is Ollama, because it can set the context window;
      anything else is spoken to as an OpenAI-compatible server (/chat/completions).
    * Only models that can call tools are used. Ollama says which ones can (/api/show); for other servers
      every listed model is tried and a refusal is reported as it comes.
    * The page keeps the conversation itself, so follow-up questions need no session on the server.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import runner

# What a model may call. open_view would open a browser window and export_query_trace writes a file.
AGENT_NAME = "ster-agent-page"
NATIVE_TOOLS = tuple(t for t in runner.STER_TOOLS if t not in ("open_view", "export_query_trace"))
MAX_STEPS = 12
MAX_CALLS_PER_STEP = 6  # a small model can ask for a dozen calls at once, mostly the same
TO_MODEL_CAP = 8000  # characters of one tool result shown to the model
NUM_CTX = int(os.environ.get("ASK_NUM_CTX", "16384"))
TIMEOUT = 900
_TRIM = (
    "_meta",
    "token usage",
    "open_view",
    "browser",
    "view_url",
    "CONSTRUCT",
)  # paragraphs written for desktop agents


# ----------------------------------------------------------------------------- talking to a model server
def _request(url: str, body: dict | None = None, timeout: float = 10) -> Any:
    req = urllib.request.Request(
        url,
        json.dumps(body).encode() if body is not None else None,
        {"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("error", detail)
            detail = detail.get("message", detail) if isinstance(detail, dict) else detail
        except ValueError:
            pass
        raise RuntimeError(f"{e.code}: {detail}"[:300]) from None


def _root(endpoint: str) -> str:
    return re.sub(r"/v1/?$", "", endpoint.rstrip("/"))


_CAPABLE_TTL = 60  # seconds a model's answer to "can you call tools" is remembered
_capable: dict[tuple[str, str], tuple[float, bool]] = {}  # (root, model) -> (when, can call tools)


def _can_call_tools(root: str, name: str) -> bool:
    hit = _capable.get((root, name))
    if hit and time.time() - hit[0] < _CAPABLE_TTL:
        return hit[1]
    try:
        ok = "tools" in (
            _request(f"{root}/api/show", {"model": name}, 10).get("capabilities") or []
        )
    except (RuntimeError, OSError, ValueError):
        ok = False
    _capable[(root, name)] = (time.time(), ok)
    return ok


def discover(endpoint: str) -> dict:
    """What a server offers: whether it answers, whether it is Ollama, and which models can call tools."""
    root, info = _root(endpoint), {"reachable": False, "api": "openai", "models": [], "all": []}
    try:
        tags = _request(f"{root}/api/tags", None, 3)
        names = [m["name"] for m in tags.get("models", [])]
        info.update(
            reachable=True,
            api="ollama",
            all=names,
            models=[n for n in names if _can_call_tools(root, n)],
        )
        return info
    except (RuntimeError, OSError, ValueError, KeyError):
        pass
    try:  # not Ollama: an OpenAI-compatible server lists its models here, and says nothing about tools
        listed = _request(f"{endpoint.rstrip('/')}/models", None, 3)
        names = [m["id"] for m in listed.get("data", [])]
        info.update(reachable=True, all=names, models=names)
    except (RuntimeError, OSError, ValueError, KeyError):
        pass
    return info


def choose_model(info: dict, wanted: str | None) -> str | None:
    if wanted:  # a server that does not say which models can call tools gets the one asked for
        return (
            wanted
            if wanted in info["models"]
            else (wanted if info["reachable"] and info["api"] != "ollama" else None)
        )
    return info["models"][0] if info["models"] else None


class OllamaAPI:
    """/api/chat: the context window can be set, and arguments come back as objects."""

    def __init__(self, endpoint: str, model: str):
        self.url, self.model = f"{_root(endpoint)}/api/chat", model

    def wire(self, transcript: list[dict]) -> list[dict]:
        out = []
        for m in transcript:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content", ""),
                        "tool_calls": [
                            {"function": {"name": c["name"], "arguments": c["arguments"]}}
                            for c in m["tool_calls"]
                        ],
                    }
                )
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_name": m["name"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def chat(self, system: str, transcript: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        body = {
            "model": self.model,
            "stream": False,
            "tools": tools,
            "options": {"num_ctx": NUM_CTX, "temperature": 0},
            "messages": [{"role": "system", "content": system}, *self.wire(transcript)],
        }
        r = _request(self.url, body, TIMEOUT)
        msg = r.get("message") or {}
        calls = [
            {
                "id": f"call_{i}",
                "name": c["function"]["name"],
                "arguments": c["function"].get("arguments") or {},
            }
            for i, c in enumerate(msg.get("tool_calls") or [])
        ]
        return {"content": msg.get("content") or "", "tool_calls": calls}, {
            "input": r.get("prompt_eval_count"),
            "output": r.get("eval_count"),
        }


class OpenAIAPI:
    """/chat/completions, as spoken by LM Studio, llama.cpp, vLLM and others."""

    def __init__(self, endpoint: str, model: str):
        self.url, self.model = f"{endpoint.rstrip('/')}/chat/completions", model

    def wire(self, transcript: list[dict]) -> list[dict]:
        out = []
        for m in transcript:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {
                                    "name": c["name"],
                                    "arguments": json.dumps(c["arguments"]),
                                },
                            }
                            for c in m["tool_calls"]
                        ],
                    }
                )
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["id"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def chat(self, system: str, transcript: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        body = {
            "model": self.model,
            "tools": tools,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, *self.wire(transcript)],
        }
        r = _request(self.url, body, TIMEOUT)
        msg = (r.get("choices") or [{}])[0].get("message") or {}
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            raw = c["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                args = {"_unparsed": raw}
            calls.append(
                {"id": c.get("id") or f"call_{i}", "name": c["function"]["name"], "arguments": args}
            )
        u = r.get("usage") or {}
        return {"content": msg.get("content") or "", "tool_calls": calls}, {
            "input": u.get("prompt_tokens"),
            "output": u.get("completion_tokens"),
        }


def api_for(endpoint: str, model: str, api: str):
    return (OllamaAPI if api == "ollama" else OpenAIAPI)(endpoint, model)


# ----------------------------------------------------------------------------- ster, as a model sees it
def trim_instructions(text: str) -> str:
    """ster's usage instructions, without the paragraphs aimed at desktop agents (metadata, token reports, browser views)."""
    keep = [p for p in re.split(r"\n\s*\n", text or "") if not any(k in p for k in _TRIM)]
    return "\n\n".join(p.strip() for p in keep)


def meta_for(instructions: str, conv_id: str, question: str, model: str | None = None) -> dict:
    """The request metadata ster's instructions ask every tool call to carry, filled in here so the model need not.

    Besides what ster asks for, the calls say who made them: this page's loop and the model it ran, so the trace
    can name both (PROV-O associates the run with them). They go under the same namespace ster's keys are in.
    """
    meta = {}
    keys = re.findall(
        r'"([\w.\-]+)/agent-(session-id|session-question|question)"', instructions or ""
    )
    for namespace, name in keys:
        meta[f"{namespace}/agent-{name}"] = conv_id if name == "session-id" else question
    if keys:
        meta[f"{keys[0][0]}/agent-name"] = AGENT_NAME
        if model:
            meta[f"{keys[0][0]}/agent-model"] = model
    return meta


def tool_definitions(ster: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        }
        for t in ster
        if t["name"] in NATIVE_TOOLS
    ]


def spoken_call(text: str, allowed: set[str]) -> dict | None:
    """Small models sometimes write a tool call as plain JSON instead of making it. Accept only the clear case."""
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        obj = json.loads(body)
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("name") not in allowed:
        return None
    args = obj.get("parameters", obj.get("arguments", {}))
    return {
        "id": "call_spoken",
        "name": obj["name"],
        "arguments": args if isinstance(args, dict) else {},
    }


# ----------------------------------------------------------------------------- the loop
@dataclass(frozen=True)
class Job:
    """What one question needs: the model server and model, the question, and where ster is."""

    endpoint: str
    model: str
    api_name: str
    prompt: str
    system_prompt: str
    ster_url: str
    ster_token: str


@dataclass(frozen=True)
class _Ster:
    """ster as the loop talks to it: where, with what headers, which tools may run, which metadata to send."""

    url: str
    headers: dict
    allowed: set[str]
    meta: dict


@dataclass(frozen=True)
class _StepCall:
    """One tool call the model asked for in a step: which step, which one of its calls, and the call."""

    step: str
    index: int
    call: dict


@dataclass
class _Memory:
    """What the loop remembers while answering: the conversation sent to the model, and the calls already made."""

    transcript: list[dict]
    already: set[str]


async def _connect(run, job: Job, headers: dict):
    """Ask ster for its instructions and tools. None (after saying why) when it does not answer."""
    try:
        init = await asyncio.to_thread(
            runner._rpc,
            job.ster_url,
            headers,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "ask-the-ontology", "version": "1"},
            },
        )
        listed = (await asyncio.to_thread(runner._rpc, job.ster_url, headers, "tools/list")).get(
            "tools", []
        )
    except Exception as exc:  # ster not answering
        await run.emit("done", status="error", error=f"ster did not answer: {exc}"[:300])
        return None
    instructions = init.get("instructions") or ""
    system = job.system_prompt + "\n\n" + trim_instructions(instructions)
    allowed = {t["name"] for t in listed if t["name"] in NATIVE_TOOLS}
    ster = _Ster(
        job.ster_url,
        headers,
        allowed,
        meta_for(instructions, run.conv["id"], job.prompt, job.model),
    )
    return system, tool_definitions(listed), ster


def _record_reply(transcript: list[dict], message: dict, allowed: set[str]) -> dict:
    """Add the model's reply to the conversation (a call it only wrote out as text becomes a real one)."""
    if not message["tool_calls"] and (spoken := spoken_call(message["content"], allowed)):
        message = {"content": "", "tool_calls": [spoken]}
    transcript.append(
        {"role": "assistant", "content": message["content"], "tool_calls": message["tool_calls"]}
    )
    return message


async def _run_call(run, asked: _StepCall, ster: _Ster, memory: _Memory) -> None:
    """Run one of the model's tool calls on ster (or say why not) and put its result in the conversation."""
    step, i, call = asked.step, asked.index, asked.call
    call_id = f"{step}-{call['id']}"
    await run.emit("tool_call", step=step, id=call_id, name=call["name"], input=call["arguments"])
    key = call["name"] + json.dumps(call["arguments"], sort_keys=True, default=str)
    if i >= MAX_CALLS_PER_STEP:
        text, is_error = (
            f"Not run: at most {MAX_CALLS_PER_STEP} tool calls per step. Ask for fewer.",
            True,
        )
    elif key in memory.already:
        text, is_error = (
            "Not run again: you already made this exact call while answering this question. Its result is earlier in the conversation; use it or try something different.",
            False,
        )
    else:
        memory.already.add(key)
        text, is_error = await _call_tool(ster.url, ster.headers, call, ster.allowed, ster.meta)
    await run.emit_tool_result(call_id, text, is_error)
    shown = (
        text
        if len(text) <= TO_MODEL_CAP
        else text[:TO_MODEL_CAP] + f"\n[... {len(text) - TO_MODEL_CAP} more characters not shown]"
    )
    memory.transcript.append(
        {"role": "tool", "id": call["id"], "name": call["name"], "content": shown}
    )


async def drive(run, job: Job):
    """Answer one question: call the model, run its tool calls against ster, repeat, then give the answer."""
    conv = run.conv
    ready = await _connect(run, job, {"Authorization": f"Bearer {job.ster_token}"})
    if ready is None:
        return
    system, tools, ster = ready
    api = api_for(job.endpoint, job.model, job.api_name)
    memory = _Memory(conv.setdefault("messages", []), set())
    memory.transcript.append({"role": "user", "content": job.prompt})
    conv["session_id"] = conv["id"]  # the page keeps the conversation itself: its id is the session
    await run.emit("session", session_id=conv["id"], model=job.model)
    totals = {"input": 0, "output": 0}
    for n in range(1, MAX_STEPS + 1):
        if getattr(run, "cancelled", False):
            return
        step = f"s{n}"
        await run.emit("step_start", step=step, model=job.model)
        try:
            message, usage = await asyncio.to_thread(api.chat, system, memory.transcript, tools)
        except Exception as exc:
            if memory.transcript and memory.transcript[-1]["role"] == "user":
                memory.transcript.pop()
            await run.emit("done", status="error", error=str(exc)[:400])
            return
        await run.emit_usage(step, usage)
        for k in totals:
            totals[k] += usage.get(k) or 0
        message = _record_reply(memory.transcript, message, ster.allowed)
        if message["content"]:
            await run.emit("text_delta", step=step, text=message["content"])
        if not message["tool_calls"]:
            run.persist()
            await run.emit(
                "done",
                status="completed",
                answer=message["content"].strip(),
                session_id=conv["id"],
                usage=totals,
            )
            return
        for i, call in enumerate(message["tool_calls"]):
            await _run_call(run, _StepCall(step, i, call), ster, memory)
    run.persist()
    await run.emit(
        "done", status="error", error=f"No answer after {MAX_STEPS} steps.", usage=totals
    )


async def _call_tool(
    ster_url: str, headers: dict, call: dict, allowed: set[str], meta: dict
) -> tuple[str, bool]:
    """Run one tool on ster and return (text, is_error). A bad call is reported to the model so it can try again."""
    name, args = call["name"], call["arguments"]
    if name not in allowed:
        return f"Unknown tool '{name}'. Available: {', '.join(sorted(allowed))}.", True
    if not isinstance(args, dict) or "_unparsed" in args:
        return "The arguments were not valid JSON. Send an object of named arguments.", True
    params: dict = {"name": name, "arguments": args}
    if meta:
        params["_meta"] = meta
    try:
        res = await asyncio.to_thread(runner._rpc, ster_url, headers, "tools/call", params, 120)
    except Exception as exc:
        return f"The tool failed: {exc}"[:300], True
    text = "".join(p.get("text", "") for p in res.get("content", []) if isinstance(p, dict))
    return text, bool(res.get("isError"))
