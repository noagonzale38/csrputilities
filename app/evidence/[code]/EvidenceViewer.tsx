"use client";

import { AlertTriangle, ExternalLink, FileImage, FileVideo, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";

type EvidenceEntry = {
  id: string;
  target_username: string;
  description: string;
  sensitive: boolean;
  visibility: "all" | "dashboard" | "roles";
  viewer_role_ids: string[];
  media_items: EvidenceMediaItem[];
  media_type: "image" | "video";
  media_url: string;
  public_url: string;
  created_at: number;
};
type EvidenceMediaItem = {
  media_source: "upload" | "link";
  media_type: "image" | "video";
  media_url: string;
  filename?: string;
};

function formatEvidenceDate(timestamp: number) {
  if (!timestamp) return "Unknown date";
  return new Date(timestamp * 1000).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function evidenceMediaItems(entry: EvidenceEntry) {
  return entry.media_items?.length
    ? entry.media_items
    : [{ media_source: "link" as const, media_type: entry.media_type, media_url: entry.media_url }];
}

function evidenceVisibilityLabel(entry: EvidenceEntry) {
  if (entry.visibility === "dashboard") return "Dashboard users";
  if (entry.visibility === "roles") return "Restricted roles";
  return "Anyone with link";
}

export default function EvidenceViewer({ code }: { code: string }) {
  const [evidence, setEvidence] = useState<EvidenceEntry | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [acceptedSensitiveWarning, setAcceptedSensitiveWarning] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const loadEvidence = async () => {
      try {
        const response = await fetch(`/api/evidence/${encodeURIComponent(code)}`, {
          headers: { Accept: "application/json" }
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload?.error || "Evidence was not found.");
        if (!cancelled) {
          setEvidence(payload.evidence);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Evidence was not found.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadEvidence();
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (loading) {
    return (
      <main className="state-page">
        <RefreshCw className="spin" />
        <p>Loading evidence...</p>
      </main>
    );
  }

  if (error || !evidence) {
    return (
      <main className="state-page access-denied-page">
        <ShieldAlert size={34} />
        <h1>Evidence unavailable</h1>
        <p>{error || "Evidence was not found."}</p>
      </main>
    );
  }

  const showSensitiveGate = evidence.sensitive && !acceptedSensitiveWarning;
  const mediaItems = evidenceMediaItems(evidence);
  const firstMediaItem = mediaItems[0];

  return (
    <main className="evidence-public-page">
      <section className="evidence-viewer">
        <header className="evidence-viewer-header">
          <div className="evidence-viewer-title">
            <div>
              <p className="auth-eyebrow">Evidence</p>
              <h1>{evidence.target_username}</h1>
            </div>
            {evidence.sensitive && <span className="evidence-badge sensitive">Sensitive</span>}
          </div>
          <p>{evidence.description}</p>
          <div className="evidence-viewer-meta">
            <span className="evidence-badge">{firstMediaItem.media_type === "video" ? <FileVideo size={14} /> : <FileImage size={14} />} {mediaItems.length} item{mediaItems.length === 1 ? "" : "s"}</span>
            <span className="evidence-badge">{formatEvidenceDate(evidence.created_at)}</span>
            <span className="evidence-badge">{evidenceVisibilityLabel(evidence)}</span>
            {!showSensitiveGate && (
              <a className="button ghost" href={firstMediaItem.media_url} target="_blank" rel="noreferrer">
                <ExternalLink size={16} />
                Open First Source
              </a>
            )}
          </div>
        </header>

        {showSensitiveGate ? (
          <section className="evidence-sensitive-gate" role="alert">
            <div>
              <AlertTriangle size={42} />
              <h2>Sensitive evidence</h2>
              <p>This evidence was marked as sensitive by staff. There may be potentially disturbing content linked here as evidence. Please only proceed if you are sure you want to continue to view this content.</p>
              <button className="button danger" onClick={() => setAcceptedSensitiveWarning(true)}>
                View Evidence
              </button>
            </div>
          </section>
        ) : (
          <section className="evidence-media-shell">
            {mediaItems.map((item, index) => (
              <div className="evidence-media-item" key={`${item.media_url}-${index}`}>
                {item.media_type === "video" ? (
                  <video src={item.media_url} controls playsInline preload="metadata" />
                ) : (
                  <img src={item.media_url} alt={`Evidence ${index + 1} for ${evidence.target_username}`} />
                )}
              </div>
            ))}
          </section>
        )}
      </section>
    </main>
  );
}
