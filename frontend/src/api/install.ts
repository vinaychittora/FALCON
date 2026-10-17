export interface AppInstallPrompt {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export async function requestAppInstall(
  event: AppInstallPrompt,
): Promise<"accepted" | "dismissed" | "failed"> {
  try {
    const [, choice] = await Promise.all([event.prompt(), event.userChoice]);
    return choice.outcome;
  } catch {
    // Browser policies or an expired one-shot prompt can reject installation.
    return "failed";
  }
}
