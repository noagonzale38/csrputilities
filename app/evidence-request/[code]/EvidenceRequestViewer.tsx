"use client";

import { Check, ExternalLink, FileImage, FileVideo, Link as LinkIcon, Plus, RefreshCw, Send, ShieldAlert, Upload, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

type EvidenceMediaItem = {
  media_source: "upload" | "link";
  media_type: "image" | "video";
  media_url: string;
  filename?: string;
};

type EvidenceRequest = {
  id: string;
  target_username: string;
  prompt: string;
  status: "open" | "closed";
  public_url: string;
  created_at: number;
  submission_count: number;
};

type EvidenceDraftMedia = {
  id: number;
  source: "upload" | "link";
  mediaType: "image" | "video";
  url: string;
  name: string;
  file?: File;
};

const MAX_EVIDENCE_MEDIA_ITEMS = 3;
const IMAGE_EVIDENCE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".webp"];
const VIDEO_EVIDENCE_EXTENSIONS = [".mp4", ".mov", ".webm", ".m4v"];

function formatEvidenceDate(timestamp: number) {
  if (!timestamp) return "Unknown date";
  return new Date(timestamp * 1000).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function mediaTypeFromName(value: string): "image" | "video" | null {
  const normalized = value.split("?")[0].split("#")[0].toLowerCase();
  if (IMAGE_EVIDENCE_EXTENSIONS.some((extension) => normalized.endsWith(extension))) return "image";
  if (VIDEO_EVIDENCE_EXTENSIONS.some((extension) => normalized.endsWith(extension))) return "video";
  return null;
}

export default function EvidenceRequestViewer({ code }: { code: string }) {
  const [requestData, setRequestData] = useState<EvidenceRequest | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [mediaDraft, setMediaDraft] = useState<EvidenceDraftMedia[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [formError, setFormError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaDraftRef = useRef<EvidenceDraftMedia[]>([]);

  useEffect(() => {
    mediaDraftRef.current = mediaDraft;
  }, [mediaDraft]);

  useEffect(() => {
    return () => {
      mediaDraftRef.current.forEach((item) => {
        if (item.source === "upload") URL.revokeObjectURL(item.url);
      });
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadRequest = async () => {
      try {
        const response = await fetch(`/api/evidence-requests/${encodeURIComponent(code)}`, {
          headers: { Accept: "application/json" }
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload?.error || "Upload request was not found.");
        if (!cancelled) {
          setRequestData(payload.request);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Upload request was not found.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadRequest();
    return () => {
      cancelled = true;
    };
  }, [code]);

  const clearMediaDraft = () => {
    mediaDraft.forEach((item) => {
      if (item.source === "upload") URL.revokeObjectURL(item.url);
    });
    setMediaDraft([]);
    setLinkDraft("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const addFiles = (files: FileList | null) => {
    if (!files?.length) return;
    const remainingSlots = MAX_EVIDENCE_MEDIA_ITEMS - mediaDraft.length;
    if (remainingSlots <= 0) {
      setFormError(`You can attach up to ${MAX_EVIDENCE_MEDIA_ITEMS} items.`);
      return;
    }

    const nextItems: EvidenceDraftMedia[] = [];
    Array.from(files).slice(0, remainingSlots).forEach((file) => {
      const mediaType =
        file.type.startsWith("video/")
          ? "video"
          : file.type.startsWith("image/")
            ? "image"
            : mediaTypeFromName(file.name);

      if (!mediaType) {
        setFormError(`${file.name} is not a supported image, GIF, or video.`);
        return;
      }

      nextItems.push({
        id: Date.now() + Math.random(),
        source: "upload",
        mediaType,
        url: URL.createObjectURL(file),
        name: file.name,
        file
      });
    });

    if (nextItems.length) setMediaDraft((current) => [...current, ...nextItems]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const addLink = () => {
    const url = linkDraft.trim();
    if (!url) return;
    if (mediaDraft.length >= MAX_EVIDENCE_MEDIA_ITEMS) {
      setFormError(`You can attach up to ${MAX_EVIDENCE_MEDIA_ITEMS} items.`);
      return;
    }

    const mediaType = mediaTypeFromName(url);
    if (!mediaType) {
      setFormError("Links must end in a supported image, GIF, or video extension.");
      return;
    }

    setMediaDraft((current) => [
      ...current,
      {
        id: Date.now() + Math.random(),
        source: "link",
        mediaType,
        url,
        name: url
      }
    ]);
    setLinkDraft("");
    setFormError("");
  };

  const removeMediaDraftItem = (id: number) => {
    setMediaDraft((current) => {
      const item = current.find((mediaItem) => mediaItem.id === id);
      if (item?.source === "upload") URL.revokeObjectURL(item.url);
      return current.filter((mediaItem) => mediaItem.id !== id);
    });
  };

  const submitRequestEvidence = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting || !requestData) return;

    if (!mediaDraft.length) {
      setFormError("Add at least one upload or media link.");
      return;
    }

    const form = event.currentTarget;
    const formData = new FormData(form);
    mediaDraft.forEach((item) => {
      if (item.file) {
        formData.append("evidence_files", item.file, item.file.name);
      } else {
        formData.append("media_urls", item.url);
      }
    });

    setSubmitting(true);
    setFormError("");

    try {
      const response = await fetch(`/api/evidence-requests/${encodeURIComponent(code)}/submit`, {
        method: "POST",
        body: formData,
        headers: { Accept: "application/json" }
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload?.ok === false) {
        throw new Error(payload?.error || "Unable to submit evidence.");
      }
      setSubmitted(true);
      setRequestData(payload.request || requestData);
      form.reset();
      clearMediaDraft();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to submit evidence.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <main className="state-page">
        <RefreshCw className="spin" />
        <p>Loading upload request...</p>
      </main>
    );
  }

  if (error || !requestData) {
    return (
      <main className="state-page access-denied-page">
        <ShieldAlert size={34} />
        <h1>Upload request unavailable</h1>
        <p>{error || "Upload request was not found."}</p>
      </main>
    );
  }

  return (
    <main className="evidence-public-page">
      <section className="evidence-viewer">
        <header className="evidence-viewer-header">
          <div className="evidence-viewer-title">
            <div>
              <p className="auth-eyebrow">Evidence Request</p>
              <h1>{requestData.target_username}</h1>
            </div>
            <span className="evidence-badge">{requestData.status}</span>
          </div>
          <p>{requestData.prompt}</p>
          <div className="evidence-viewer-meta">
            <span className="evidence-badge">{requestData.submission_count} submission{requestData.submission_count === 1 ? "" : "s"}</span>
            <span className="evidence-badge">{formatEvidenceDate(requestData.created_at)}</span>
            <a className="button ghost" href={requestData.public_url} target="_blank" rel="noreferrer">
              <ExternalLink size={16} />
              Open Link
            </a>
          </div>
        </header>

        {requestData.status !== "open" ? (
          <section className="evidence-sensitive-gate" role="alert">
            <div>
              <ShieldAlert size={42} />
              <h2>Request closed</h2>
              <p>This upload request is no longer accepting evidence.</p>
            </div>
          </section>
        ) : submitted ? (
          <section className="evidence-sensitive-gate" role="status">
            <div>
              <Check size={42} />
              <h2>Evidence sent</h2>
              <p>Your upload was submitted to staff successfully. You can close this page now.</p>
            </div>
          </section>
        ) : (
          <form className="evidence-submit-form" onSubmit={submitRequestEvidence}>
            <label>
              Your username
              <input name="submitter_name" placeholder="Discord username" required maxLength={100} />
            </label>
            <label>
              Notes
              <textarea name="description" placeholder="Optional context for staff" maxLength={1500} />
            </label>
            <label className="file-field">
              <Upload size={18} />
              <span>Upload up to {MAX_EVIDENCE_MEDIA_ITEMS} images, GIFs, or videos</span>
              <input ref={fileInputRef} type="file" accept="image/*,video/*,.gif" multiple onChange={(event) => addFiles(event.target.files)} />
            </label>
            <div className="evidence-link-row">
              <label className="input-with-icon">
                <LinkIcon size={18} />
                <input
                  value={linkDraft}
                  onChange={(event) => setLinkDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addLink();
                    }
                  }}
                  placeholder="Or add a direct image/video link"
                />
              </label>
              <button type="button" className="button ghost" onClick={addLink} disabled={!linkDraft.trim() || mediaDraft.length >= MAX_EVIDENCE_MEDIA_ITEMS}>
                <Plus size={16} />
                Add
              </button>
            </div>
            {mediaDraft.length > 0 && (
              <div className="evidence-draft-grid">
                {mediaDraft.map((item) => (
                  <article className="evidence-draft-card" key={item.id}>
                    <div className="evidence-draft-preview">
                      {item.mediaType === "video" ? <video src={item.url} muted playsInline /> : <img src={item.url} alt="" />}
                    </div>
                    <div>
                      <strong>{item.source === "upload" ? item.name : "Linked evidence"}</strong>
                      <span>{item.mediaType} | {item.source}</span>
                    </div>
                    <button type="button" className="icon-button danger" aria-label={`Remove ${item.name}`} onClick={() => removeMediaDraftItem(item.id)}>
                      <X size={16} />
                    </button>
                  </article>
                ))}
              </div>
            )}
            {formError && <div className="theme-alert">{formError}</div>}
            <button className="button primary" disabled={submitting || !mediaDraft.length}>
              {submitting ? <RefreshCw className="spin" size={16} /> : <Send size={16} />}
              Submit Evidence
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
