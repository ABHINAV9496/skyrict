"use client";

import { useState } from "react";
import { CheckCircle2, MessageSquareText } from "lucide-react";

const CATEGORIES = ["Bug report", "Feature request", "Search quality", "Something else"];

export default function FeedbackPage() {
  const [category, setCategory] = useState<string>(CATEGORIES[0]);
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!message.trim()) return;
    setSent(true);
  };

  if (sent) {
    return (
      <div className="mx-auto max-w-lg rounded-2xl border border-border bg-card p-10 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400">
          <CheckCircle2 aria-hidden="true" className="size-6" />
        </div>
        <h1 className="mt-4 font-display text-xl font-semibold tracking-tight text-foreground">
          Thanks for the feedback
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Your note has been recorded. We read everything and use it to shape
          what ships next.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg">
      <header className="text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary/15 text-primary">
          <MessageSquareText aria-hidden="true" className="size-6" />
        </div>
        <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Send feedback
        </h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          Tell us what&apos;s working, what&apos;s not, or what you&apos;d love
          to see next in Skyrict GMIE.
        </p>
      </header>

      <form onSubmit={submit} className="mt-8 space-y-4">
        <div>
          <label htmlFor="feedback-category" className="mb-1.5 block text-sm font-medium text-foreground">
            Category
          </label>
          <select
            id="feedback-category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {CATEGORIES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="feedback-message" className="mb-1.5 block text-sm font-medium text-foreground">
            Message
          </label>
          <textarea
            id="feedback-message"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={5}
            placeholder="What's on your mind?"
            className="w-full rounded-lg border border-input bg-card px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>

        <button
          type="submit"
          className="h-10 w-full rounded-lg bg-primary text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          disabled={!message.trim()}
        >
          Send feedback
        </button>
      </form>
    </div>
  );
}
