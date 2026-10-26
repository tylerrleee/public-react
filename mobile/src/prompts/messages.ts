import messages from './messages.json';

// Bundled copy of the approved message bank, generated from the backend's
// REACTprompts.csv by `manage.py dump_prompt_messages`. Pushes carry only a
// prompt_id, so message text never leaves the device.
const MESSAGES: Record<string, string> = messages;

export function promptMessage(promptId: string | null | undefined): string | undefined {
  return promptId ? MESSAGES[promptId] : undefined;
}
