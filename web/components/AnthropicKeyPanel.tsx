"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { Badge, Notice, Panel, Section } from "./ui";

/**
 * Bring-your-own Claude key.
 *
 * Optional by design: findings are deterministic either way, and a key only
 * adds the written summary. Nobody is blocked at onboarding by a second signup.
 *
 * The copy says where a key comes from, because "get an API key" is not a
 * searchable instruction for someone who has never used the API - and the part
 * people actually get stuck on is that API billing is separate from a Claude.ai
 * subscription.
 */
export function AnthropicKeyPanel({
  hint,
  onChange,
}: {
  hint: string | null;
  onChange: () => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const result = await api<{ hint: string }>("/api/settings/anthropic-key", {
        method: "POST",
        body: { key: value.trim() },
      });
      setValue("");
      setSaved(`Key saved and verified (${result.hint}).`);
      await onChange();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save that key.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api("/api/settings/anthropic-key", { method: "DELETE" });
      setSaved("Key removed. Scans will report findings without a written summary.");
      await onChange();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove that key.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section eyebrow="Claude API key (optional)">
      {error ? <Notice tone="error">{error}</Notice> : null}
      {saved ? <Notice tone="ok">{saved}</Notice> : null}

      <Panel>
        <p style={{ marginTop: error || saved ? 16 : 0 }}>
          {hint ? <Badge tone="ok">Key installed &middot; {hint}</Badge> : <Badge>No key</Badge>}
        </p>
        <p className="muted small" style={{ marginTop: 10 }}>
          {hint
            ? "Replace it by pasting a new one, or remove it to go back to plain findings."
            : "Findings are deterministic either way. A key adds a written summary that prioritises them."}
        </p>

        {!hint ? (
          <p className="small dim" style={{ marginTop: 12 }}>
            Create one in{" "}
            <a
              href="https://console.anthropic.com/settings/keys"
              target="_blank"
              rel="noopener noreferrer"
            >
              the Anthropic console
            </a>
            . API billing is separate from a Claude.ai subscription, which doesn&rsquo;t
            include API access.
          </p>
        ) : null}

        <div className="btn-row" style={{ marginTop: 16 }}>
          <label className="label skip" htmlFor="anthropic-key">
            Anthropic API key
          </label>
          <input
            id="anthropic-key"
            className="field mono"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="sk-ant-..."
            value={value}
            onChange={(event) => setValue(event.target.value)}
            style={{ flex: 1, minWidth: 240 }}
          />
          <button className="btn" type="button" disabled={busy || !value.trim()} onClick={save}>
            {busy ? "Checking…" : "Save key"}
          </button>
          {hint ? (
            <button className="btn secondary" type="button" disabled={busy} onClick={remove}>
              Remove key
            </button>
          ) : null}
        </div>

        <p className="small dim" style={{ marginTop: 14 }}>
          Checked against the Anthropic API before it is stored, encrypted at rest, never
          logged, and never placed in the environment your repository&rsquo;s build tools
          inherit. Usage is billed to your own Anthropic account.
        </p>
      </Panel>
    </Section>
  );
}
