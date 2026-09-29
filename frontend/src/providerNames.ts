const names: Record<string, string> = {
  google: "Google",
  openai: "OpenAI",
  anthropic: "Anthropic",
  deepseek: "DeepSeek",
  openai_compatible: "OpenAI-compatible",
};

export function providerName(provider: string) {
  return names[provider] ?? provider.charAt(0).toLocaleUpperCase() + provider.slice(1);
}
