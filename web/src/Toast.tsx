/** A message that cannot be missed by not looking for it.
 *
 *  Errors belong where the eye already is. A banner at the top of a long
 *  document is invisible to anyone who is scrolled down -- which is exactly
 *  where they are when something fails, because they were reading the thing
 *  that failed. The banner stays in the flow as the record; this is what they
 *  actually see. */

import { X } from "lucide-react";

export interface Notice {
  id: string;
  tone: "bad" | "good";
  text: string;
}

export function Toasts({
  notices,
  onDismiss,
}: {
  notices: Notice[];
  onDismiss: (id: string) => void;
}) {
  if (!notices.length) return null;
  return (
    <div
      // Bottom centre: the document's action buttons live at the bottom, and a
      // toast there is next to the thing the person was about to press.
      className="no-print pointer-events-none fixed inset-x-0 bottom-6 z-50 flex flex-col items-center gap-2 px-4"
    >
      {notices.map((notice) => (
        <div
          key={notice.id}
          role="alert"
          aria-live={notice.tone === "bad" ? "assertive" : "polite"}
          className={`pointer-events-auto flex max-w-xl items-start gap-3 rounded border px-4 py-3 ${
            notice.tone === "bad"
              ? "border-red-300 bg-red-50 text-red-900"
              : "border-accent-300 bg-accent-50 text-accent-900"
          }`}
        >
          <p className="min-w-0 flex-1 text-sm">{notice.text}</p>
          <button
            onClick={() => onDismiss(notice.id)}
            aria-label="Закрыть"
            className="focus-ring relative -mr-1 grid h-6 w-6 shrink-0 place-items-center rounded hover:bg-black/5 before:absolute before:-inset-2.5 before:content-['']"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
