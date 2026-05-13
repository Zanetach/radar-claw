import http from "node:http";
import { URL } from "node:url";

const host = process.env.WEBBRIDGE_HOST || "127.0.0.1";
const port = Number(process.env.WEBBRIDGE_PORT || "10086");
const cdpBase = process.env.CDP_BASE || "http://127.0.0.1:9222";

let nextId = 1;

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function cdpTabs() {
  return getJson(`${cdpBase}/json`);
}

async function newCdpPage(url = "https://x.com/home") {
  const response = await fetch(`${cdpBase}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function activePage() {
  const tabs = await cdpTabs();
  const page = tabs.find((tab) => tab.type === "page" && tab.webSocketDebuggerUrl);
  return page || newCdpPage();
}

function connectWebSocket(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    ws.addEventListener("open", () => resolve(ws), { once: true });
    ws.addEventListener("error", () => reject(new Error("websocket connection failed")), { once: true });
  });
}

async function cdpCall(ws, method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    const onMessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.id !== id) return;
      ws.removeEventListener("message", onMessage);
      if (payload.error) {
        reject(new Error(payload.error.message || "cdp error"));
      } else {
        resolve(payload.result);
      }
    };
    ws.addEventListener("message", onMessage);
    setTimeout(() => {
      ws.removeEventListener("message", onMessage);
      reject(new Error(`cdp timeout: ${method}`));
    }, 60000);
  });
}

async function withPage(callback) {
  const page = await activePage();
  const ws = await connectWebSocket(page.webSocketDebuggerUrl);
  try {
    await cdpCall(ws, "Runtime.enable");
    await cdpCall(ws, "Page.enable");
    return await callback(ws, page);
  } finally {
    ws.close();
  }
}

async function navigate(url) {
  return withPage(async (ws) => {
    await cdpCall(ws, "Page.navigate", { url });
    return null;
  });
}

async function evaluate(code) {
  return withPage(async (ws) => {
    const result = await cdpCall(ws, "Runtime.evaluate", {
      expression: code,
      awaitPromise: true,
      returnByValue: true,
      userGesture: false,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "evaluation failed");
    }
    const remote = result.result || {};
    if (Object.prototype.hasOwnProperty.call(remote, "value")) {
      return remote.value;
    }
    return remote.description ?? null;
  });
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host}`);
    if (request.method === "GET" && url.pathname === "/status") {
      const page = await activePage();
      sendJson(response, 200, {
        reachable: true,
        cdp_base: cdpBase,
        title: page.title,
        url: page.url,
      });
      return;
    }
    if (request.method === "POST" && url.pathname === "/command") {
      const body = await readBody(request);
      const action = body.action;
      const args = body.args || {};
      if (action === "navigate") {
        await navigate(args.url);
        sendJson(response, 200, { ok: true, data: null });
        return;
      }
      if (action === "evaluate") {
        const data = await evaluate(args.code);
        sendJson(response, 200, { ok: true, data });
        return;
      }
      sendJson(response, 400, { ok: false, error: { code: "unsupported_action", message: action } });
      return;
    }
    sendJson(response, 404, { ok: false, error: { code: "not_found" } });
  } catch (error) {
    sendJson(response, 500, {
      ok: false,
      error: {
        code: "webbridge_error",
        message: error?.message || String(error),
      },
    });
  }
});

server.listen(port, host, () => {
  console.log(`CDP WebBridge listening on http://${host}:${port}, cdp=${cdpBase}`);
});
