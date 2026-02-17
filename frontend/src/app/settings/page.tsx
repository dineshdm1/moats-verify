"use client";

import { useEffect, useState } from "react";
import { getSettings, updateLLMSettings, testLLM } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

const providers = [
  { value: "openrouter", label: "OpenRouter" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "ollama", label: "Local (Ollama / LM Studio)" },
  { value: "custom", label: "Custom Endpoint" },
];

export default function SettingsPage() {
  const [provider, setProvider] = useState("openrouter");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [chatModel, setChatModel] = useState("");
  const [embedModel, setEmbedModel] = useState("");
  const [testResult, setTestResult] = useState<{ status: string; message?: string; error?: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => {
        const llm = s.llm as Record<string, string>;
        if (llm.provider) setProvider(llm.provider);
        if (llm.api_key) setApiKey(llm.api_key);
        if (llm.base_url) setBaseUrl(llm.base_url);
        if (llm.chat_model) setChatModel(llm.chat_model);
        if (llm.embedding_model) setEmbedModel(llm.embedding_model);
      })
      .catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateLLMSettings({
        provider,
        api_key: apiKey,
        base_url: baseUrl,
        chat_model: chatModel,
        embedding_model: embedModel,
      });
      setTestResult({ status: "ok", message: "Settings saved" });
    } catch (e) {
      setTestResult({ status: "error", error: e instanceof Error ? e.message : "Save failed" });
    }
    setSaving(false);
  };

  const handleTest = async () => {
    setTestResult(null);
    try {
      // Save first, then test
      await handleSave();
      const result = await testLLM();
      setTestResult(result);
    } catch (e) {
      setTestResult({ status: "error", error: e instanceof Error ? e.message : "Test failed" });
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-lg font-semibold text-foreground">SETTINGS</h1>

      <Card className="p-4">
        <Label className="text-xs uppercase tracking-wider text-muted-foreground">Provider</Label>
        <div className="mt-2 space-y-2">
          {providers.map((p) => (
            <label key={p.value} className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
              <input
                type="radio"
                name="provider"
                value={p.value}
                checked={provider === p.value}
                onChange={() => setProvider(p.value)}
                className="accent-primary"
              />
              {p.label}
            </label>
          ))}
        </div>
      </Card>

      {provider === "ollama" ? (
        <Card className="space-y-3 p-4">
          <div>
            <Label>Endpoint</Label>
            <Input
              value={baseUrl || "http://localhost:11434"}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://localhost:11434"
            />
          </div>
          <div>
            <Label>Chat Model</Label>
            <Input
              value={chatModel || "llama3.2:latest"}
              onChange={(e) => setChatModel(e.target.value)}
              placeholder="llama3.2:latest"
            />
          </div>
          <div>
            <Label>Embedding Model</Label>
            <Input
              value={embedModel || "nomic-embed-text"}
              onChange={(e) => setEmbedModel(e.target.value)}
              placeholder="nomic-embed-text"
            />
          </div>
        </Card>
      ) : (
        <Card className="space-y-3 p-4">
          <div>
            <Label>API Key</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
          </div>
          <div>
            <Label>Base URL</Label>
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={
                provider === "openrouter"
                  ? "https://openrouter.ai/api/v1"
                  : provider === "openai"
                    ? "https://api.openai.com/v1"
                    : "https://api.anthropic.com/v1"
              }
            />
          </div>
          <div>
            <Label>Chat Model</Label>
            <Input
              value={chatModel}
              onChange={(e) => setChatModel(e.target.value)}
              placeholder={provider === "openrouter" ? "xiaomi/mimo-v2-flash" : "gpt-4o-mini"}
            />
          </div>
          <div>
            <Label>Embedding Model</Label>
            <Input
              value={embedModel}
              onChange={(e) => setEmbedModel(e.target.value)}
              placeholder={provider === "openrouter" ? "qwen/qwen3-embedding-8b" : "text-embedding-3-small"}
            />
          </div>
        </Card>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={handleTest}>Test Connection</Button>
        <Button variant="outline" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
        {testResult && (
          <Badge variant={testResult.status === "ok" ? "default" : "destructive"}>
            {testResult.status === "ok" ? testResult.message || "Connected" : testResult.error || "Failed"}
          </Badge>
        )}
      </div>
    </div>
  );
}
