import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

// Copies the report's plain text (not the rendered HTML) to the
// clipboard, so pasting it elsewhere (an email, a ticket, Slack) gives
// clean Markdown/plain text rather than an HTML blob.
function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API unavailable (older browser / non-HTTPS context) -
      // fall back to a hidden textarea + execCommand.
      const el = document.createElement("textarea");
      el.value = text;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <button type="button" className="copy-btn" onClick={handleCopy}>
      {copied ? "Copied" : "Copy report"}
    </button>
  );
}

// A single console entry. `role` is "user" | "error" | "pending" | "report".
// Rendered as a labeled, bordered block rather than a chat bubble - this is
// a diagnostics console for R&D/Service engineers, not a consumer chat app.
function Entry({ msg, index }) {
  const tag = String(index + 1).padStart(2, "0");

  if (msg.role === "user") {
    return (
      <div className="entry entry-user">
        <div className="entry-label">Q{tag} / request</div>
        <div className="entry-body">{msg.text}</div>
      </div>
    );
  }

  if (msg.role === "error") {
    return (
      <div className="entry entry-error">
        <div className="entry-label">R{tag} / error</div>
        <div className="entry-body">{msg.text}</div>
      </div>
    );
  }

  if (msg.role === "pending") {
    return (
      <div className="entry entry-pending">
        <div className="entry-label">R{tag} / running</div>
        <div className="dots"><span className="dot" /><span className="dot" /><span className="dot" /></div>
      </div>
    );
  }

  // role === "report"
  const r = msg.report;
  return (
    <div className="entry">
      <div className="entry-label">
        R{tag} / report
        <CopyButton text={r.report_text} />
      </div>
      <div className="entry-body">
        {r.report_html ? (
          <div className="report-text" dangerouslySetInnerHTML={{ __html: r.report_html }} />
        ) : (
          // Fallback for older cached responses that don't carry
          // report_html yet - still readable, just unstyled Markdown.
          <pre className="report-text-raw">{r.report_text}</pre>
        )}

        {r.charts?.length > 0 && (
          <>
            <hr className="section-rule" />
            <p className="section-label">Charts</p>
            <div className="chart-grid">
              {r.charts.map((c, i) => (
                <figure className="chart-card" key={i}>
                  {/* Charts render at a fixed, readable card size (see
                      .chart-card in styles.css) rather than at the PNG's
                      native resolution - a torque histogram rendered at
                      full size could otherwise dominate the whole page. */}
                  <img src={c.image} alt={c.tool} loading="lazy" />
                  <figcaption>{c.tool.replace(/_/g, " ")}</figcaption>
                </figure>
              ))}
            </div>
          </>
        )}

        {r.tool_calls?.length > 0 && (
          <>
            <hr className="section-rule" />
            <details className="tool-trace">
              <summary>{r.tool_calls.length} tool call(s) made by the agent</summary>
              <ol>
                {r.tool_calls.map((t, i) => (
                  <li key={i}>
                    <code>{t.tool}({JSON.stringify(t.input)})</code>
                  </li>
                ))}
              </ol>
            </details>
          </>
        )}

        <hr className="section-rule" />
        <div className="report-downloads">
          <a href={api.reportFileUrl(r.report_id, "md")} target="_blank" rel="noreferrer">Markdown</a>
          <a href={api.reportFileUrl(r.report_id, "html")} target="_blank" rel="noreferrer">HTML</a>
          <a href={api.reportFileUrl(r.report_id, "pdf")} target="_blank" rel="noreferrer">PDF</a>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [pools, setPools] = useState([]);
  const [pool, setPool] = useState("");
  const [presets, setPresets] = useState([]);
  const [tools, setTools] = useState([]);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    api.getPools().then((d) => {
      setPools(d.pools);
      if (d.pools.length) setPool(d.pools[0]);
    }).catch(() => {});
    api.getPresets().then((d) => setPresets(d.presets)).catch(() => {});
    api.getTools().then((d) => setTools(d.tools)).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function insertPreset(prompt) {
    // Clicking a preset button inserts the ready-made prompt into the
    // input box rather than sending it immediately, so it can be
    // reviewed/edited first - matches how a normal chat input behaves.
    setInput(prompt);
  }

  async function send() {
    const query = input.trim();
    if (!query || busy) return;
    setMessages((m) => [...m, { role: "user", text: query }, { role: "pending" }]);
    setInput("");
    setBusy(true);
    try {
      const report = await api.ask(query, pool);
      setMessages((m) => [...m.slice(0, -1), { role: "report", report }]);
    } catch (e) {
      setMessages((m) => [...m.slice(0, -1), { role: "error", text: e.message }]);
    } finally {
      setBusy(false);
    }
  }

  async function runPresetDirect(kind) {
    if (busy) return;
    const preset = presets.find((p) => p.kind === kind);
    setMessages((m) => [...m, { role: "user", text: `[preset] ${preset?.prompt || kind}` }, { role: "pending" }]);
    setBusy(true);
    try {
      const report = await api.runReport(kind, pool);
      setMessages((m) => [...m.slice(0, -1), { role: "report", report }]);
    } catch (e) {
      setMessages((m) => [...m.slice(0, -1), { role: "error", text: e.message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="panel-head">
          <h1>AROL Telemetry Report Agent</h1>
          <div className="panel-sub">MCC777 · Equatorque capping diagnostics</div>
        </div>

        <div className="panel-body">
          <div>
            <label className="field-label">Dataset pool</label>
            <select value={pool} onChange={(e) => setPool(e.target.value)}>
              {pools.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label">Quick reports</label>
            <div className="preset-list">
              {presets.map((p) => (
                <div className="preset-row" key={p.kind}>
                  <button className="preset-run" onClick={() => runPresetDirect(p.kind)} disabled={busy}>
                    Run {p.kind}
                  </button>
                  <button className="preset-insert" onClick={() => insertPreset(p.prompt)} title="Insert prompt into chat">
                    ✎
                  </button>
                </div>
              ))}
            </div>
          </div>

          <p className="hint">
            &ldquo;Run&rdquo; generates the report immediately. The pencil icon
            inserts the prompt into the request box so you can edit it first.
          </p>

          <div className="tool-count">
            <strong>{tools.length}</strong> analytics tools registered<br />
            available to the agent for autonomous selection
          </div>
        </div>
      </aside>

      <main className="chat">
        <div className="statusbar">
          <span className={`led${busy ? " busy" : ""}`} />
          <span>{busy ? "AGENT RUNNING" : "IDLE"}</span>
          <span className="divider">|</span>
          <span>POOL <strong>{pool || "—"}</strong></span>
        </div>

        <div className="messages">
          {messages.length === 0 && (
            <div className="empty-state">
              Ask a question about the loaded dataset, e.g. &ldquo;Which head shows
              the lowest success rate?&rdquo; or run a quick report from the panel on the left.
            </div>
          )}
          {messages.map((m, i) => <Entry msg={m} index={i} key={i} />)}
          <div ref={bottomRef} />
        </div>

        <div className="composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask about the telemetry data..."
            rows={2}
          />
          <button onClick={send} disabled={busy || !input.trim()}>Send</button>
        </div>
      </main>
    </div>
  );
}
