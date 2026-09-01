"use client";

import { useCallback, useRef, useState } from "react";
import {
  ArrowUp,
  FileText,
  FolderUp,
  Image,
  LoaderCircle,
  Paperclip,
  Plus,
  Square,
  X,
} from "lucide-react";

import { AiGlyph } from "@/components/brand/logo";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ChatAttachment } from "@/lib/chat/use-agent-chat";
import { cn } from "@/lib/utils";

function newId(): string {
  return `att-${crypto.randomUUID()}`;
}

/** Return a readable label for the file type category. */
function fileTypeLabel(mimeType: string): string {
  if (mimeType.startsWith("image/")) return "Image";
  if (mimeType === "application/pdf") return "PDF";
  if (mimeType.includes("spreadsheet") || mimeType.includes("csv") || mimeType.includes("excel"))
    return "Spreadsheet";
  if (mimeType.includes("text/")) return "Document";
  if (mimeType.includes("word") || mimeType.includes("document")) return "Document";
  return "File";
}

/** Return the appropriate icon for a file type. */
function FileIcon({ mimeType, className }: { mimeType: string; className?: string }) {
  // eslint-disable-next-line jsx-a11y/alt-text -- lucide Image is an SVG icon, not <img>
  if (mimeType.startsWith("image/")) return <Image aria-hidden="true" className={className} />;
  if (mimeType === "application/pdf")
    return <span className={cn("font-bold text-red-500", className)}>PDF</span>;
  return <FileText aria-hidden="true" className={className} />;
}

/** Convert a File into a ChatAttachment. */
function fileToAttachment(file: File): ChatAttachment {
  return {
    id: newId(),
    name: file.name,
    type: file.type,
    size: file.size,
    previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined,
  };
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ------------------------------------------------------------------ */
/*  File preview card                                                  */
/* ------------------------------------------------------------------ */

function FilePreviewCard({
  attachment,
  onRemove,
}: {
  attachment: ChatAttachment;
  onRemove: () => void;
}) {
  return (
    <div className="flex min-w-0 max-w-[260px] items-center gap-2.5 rounded-xl border border-border/60 bg-background/80 px-3 py-2 text-sm backdrop-blur-sm">
      {attachment.previewUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={attachment.previewUrl}
          alt=""
          className="size-8 shrink-0 rounded-md object-cover"
        />
      ) : (
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
          <FileIcon mimeType={attachment.type} className="size-4 text-muted-foreground" />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-foreground">{attachment.name}</p>
        <p className="text-[11px] text-muted-foreground">
          {fileTypeLabel(attachment.type)}
          {attachment.size > 0 ? ` · ${formatSize(attachment.size)}` : ""}
        </p>
      </div>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${attachment.name}`}
        className="flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <X aria-hidden="true" className="size-3" />
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ChatComposer                                                       */
/* ------------------------------------------------------------------ */

export function ChatComposer({
  onSend,
  onStop,
  placeholder = "Message Skyrict…",
}: {
  onSend: (content: string, attachments?: ChatAttachment[]) => Promise<void>;
  /** When provided while a turn is streaming, the send button becomes Stop. */
  onStop?: () => void;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const dragCounterRef = useRef(0);

  const addFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files).map(fileToAttachment);
    setAttachments((prev) => [...prev, ...incoming]);
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const next = prev.filter((a) => a.id !== id);
      // Revoke object URLs to avoid memory leaks.
      const removed = prev.find((a) => a.id === id);
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
      return next;
    });
  }, []);

  const submit = useCallback(async () => {
    const content = value.trim();
    if ((!content && attachments.length === 0) || sending) return;
    setSending(true);
    const pending = attachments;
    setAttachments([]);
    setValue("");
    try {
      await onSend(content || "Uploaded files", pending.length > 0 ? pending : undefined);
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  }, [value, sending, onSend, attachments]);

  const canStop = sending && onStop !== undefined;

  /* Drag-and-drop handlers */
  const handleDragEnter = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    dragCounterRef.current += 1;
    if (event.dataTransfer.types.includes("Files")) setDragging(true);
  }, []);

  const handleDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
      dragCounterRef.current = 0;
      setDragging(false);
      if (event.dataTransfer.files.length > 0) {
        addFiles(event.dataTransfer.files);
      }
    },
    [addFiles],
  );

  /* Ctrl+U keyboard shortcut to open file picker */
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "u") {
        event.preventDefault();
        fileInputRef.current?.click();
      }
      if (event.key === "Enter" && !event.shiftKey && !canStop) {
        event.preventDefault();
        void submit();
      }
    },
    [canStop, submit],
  );

  return (
    <div
      className="mx-auto w-full max-w-[44rem]"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Hidden file inputs */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => {
          if (event.target.files) addFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <input
        ref={folderInputRef}
        type="file"
        // @ts-expect-error -- webkitdirectory is a non-standard attribute for folder upload
        webkitdirectory=""
        multiple
        className="hidden"
        onChange={(event) => {
          if (event.target.files) addFiles(event.target.files);
          event.target.value = "";
        }}
      />

      <div
        className={cn(
          "flex flex-col rounded-[1.5rem] border border-border/60 bg-muted/30 p-2 shadow-sm transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20 dark:border-muted-foreground/15 dark:focus-within:border-muted-foreground/30",
          dragging && "border-primary/50 ring-3 ring-primary/20",
        )}
      >
        {/* Drag-and-drop overlay */}
        {dragging ? (
          <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-primary/40 bg-primary/5 py-6 text-sm text-primary">
            <Paperclip aria-hidden="true" className="mr-2 size-4" />
            Drop files here
          </div>
        ) : null}

        {/* File preview cards */}
        {attachments.length > 0 && !dragging ? (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachments.map((attachment) => (
              <FilePreviewCard
                key={attachment.id}
                attachment={attachment}
                onRemove={() => removeAttachment(attachment.id)}
              />
            ))}
          </div>
        ) : null}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder={placeholder}
          aria-label="Message"
          className="max-h-40 min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-sm text-foreground outline-none placeholder:text-muted-foreground/80"
        />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label="Attach files"
                  title="Attach files"
                  className="flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
                >
                  <Plus aria-hidden="true" className="size-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" sideOffset={8}>
                <DropdownMenuItem onSelect={() => fileInputRef.current?.click()}>
                  <Paperclip aria-hidden="true" />
                  <span>Add files or photos</span>
                  <span className="ml-auto text-[11px] text-muted-foreground">Ctrl+U</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => folderInputRef.current?.click()}>
                  <FolderUp aria-hidden="true" />
                  <span>Upload folder</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <span className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium text-muted-foreground">
              <AiGlyph aria-hidden="true" className="size-3.5 text-primary" />
              Skyrict Agent
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                if (canStop) onStop();
                else void submit();
              }}
              disabled={canStop ? false : !value.trim() && attachments.length === 0 || sending}
              aria-label={canStop ? "Stop generating" : "Send message"}
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity hover:bg-primary/80 disabled:opacity-40"
            >
              {canStop ? (
                <Square aria-hidden="true" className="size-3.5 fill-current" />
              ) : sending ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <ArrowUp aria-hidden="true" className="size-4" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
