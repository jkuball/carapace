import assert from "node:assert/strict";
import test from "node:test";

import { buildPlatformSettingsPatch } from "./platform-settings-view";

type PlatformDraft = Parameters<typeof buildPlatformSettingsPatch>[0];

function translate(key: string, values?: Record<string, string | number>): string {
  if (!values) return key;
  return Object.entries(values).reduce((message, [name, value]) => message.replaceAll(`{${name}}`, String(value)), key);
}

function draftWithModel(model: PlatformDraft["models"][number]): PlatformDraft {
  const id = model.id || `${model.provider}:${model.name}`;
  return {
    defaultModels: {
      agent: id,
      sentinel: id,
      title: id,
    },
    budget: {
      input_tokens: "",
      output_tokens: "",
      cost_usd: "",
      tool_calls: "",
    },
    models: [model],
  };
}

test("buildPlatformSettingsPatch omits OpenAI-only fields for other providers", () => {
  const patch = buildPlatformSettingsPatch(
    draftWithModel({
      rowId: "model-1",
      provider: "anthropic",
      name: "claude-haiku-4-5",
      id: "",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "128",
      baseUrl: "http://127.0.0.1:1234/v1",
      apiKeySource: "raw",
      apiKeyValue: "",
      apiKeyConfigured: true,
      apiKeyConfiguredSource: "raw",
    }),
    translate,
  );

  const model = patch.available_models[0]!;
  assert.equal(model.provider, "anthropic");
  assert.equal(Object.hasOwn(model, "thinking_budget_tokens"), false);
  assert.equal(Object.hasOwn(model, "base_url"), false);
  assert.equal(Object.hasOwn(model, "api_key"), false);
});

test("buildPlatformSettingsPatch reuses configured raw OpenAI secrets", () => {
  const patch = buildPlatformSettingsPatch(
    draftWithModel({
      rowId: "model-1",
      provider: "openai",
      name: "gpt-4o-mini",
      id: "local:test",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "",
      baseUrl: "http://127.0.0.1:1234/v1",
      apiKeySource: "raw",
      apiKeyValue: "",
      apiKeyConfigured: true,
      apiKeyConfiguredSource: "raw",
    }),
    translate,
  );

  assert.deepEqual(patch.available_models[0]?.api_key, { source: "raw" });
});

test("buildPlatformSettingsPatch includes OpenRouter API key fields without base URL", () => {
  const patch = buildPlatformSettingsPatch(
    draftWithModel({
      rowId: "model-1",
      provider: "openrouter",
      name: "anthropic/claude-sonnet-4.5",
      id: "openrouter:sonnet",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "128",
      baseUrl: "https://openrouter.ai/api/v1",
      apiKeySource: "env",
      apiKeyValue: "OPENROUTER_API_KEY",
      apiKeyConfigured: false,
      apiKeyConfiguredSource: "none",
    }),
    translate,
  );

  const model = patch.available_models[0]!;
  assert.equal(model.provider, "openrouter");
  assert.deepEqual(model.api_key, { source: "env", value: "OPENROUTER_API_KEY" });
  assert.equal(Object.hasOwn(model, "base_url"), false);
  assert.equal(Object.hasOwn(model, "thinking_budget_tokens"), false);
});
