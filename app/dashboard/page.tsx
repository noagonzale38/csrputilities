"use client";

import {
  Ban,
  Bot,
  ChevronDown,
  Check,
  Copy,
  Database,
  Download,
  FileText,
  Filter,
  Gauge,
  LogOut,
  Megaphone,
  Palette,
  Plus,
  RefreshCw,
  Redo2,
  Save,
  Search,
  Send,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Star,
  Trash2,
  Undo2,
  Upload,
  X,
  UserMinus,
  Users
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Role = { id: string; name: string; position: number; color: string };
type Channel = { id: string; name: string; position: number };
type Feature = { key: string; label: string };
type ThemeColors = {
  background: string;
  backgroundSoft: string;
  panel: string;
  panelStrong: string;
  field: string;
  foreground: string;
  muted: string;
  mutedStrong: string;
  primary: string;
  primaryStrong: string;
  primaryInk: string;
  secondary: string;
  highlight: string;
  destructive: string;
};
type ThemeDefinition = {
  id: string;
  name: string;
  description: string;
  author: string;
  tags: string[];
  downloads: number;
  updated: string;
  rating: number;
  source: "marketplace" | "custom";
  colors: ThemeColors;
};
type ThemeDraft = Pick<ThemeDefinition, "name" | "description" | "tags" | "colors">;
type ThemeCatalogResponse = {
  marketplace: unknown[];
  mine: unknown[];
};
type DashboardData = {
  member: { display_name: string; avatar_url: string };
  guild: { name: string; icon_url: string | null };
  stats: Record<string, number | string | null>;
  settings: Record<string, any>;
  readable_settings: Record<string, any>;
  permissions_data: { full_access_roles: string[]; features: Record<string, string[]> };
  features: Feature[];
  feature_access: Record<string, boolean>;
  roles: Role[];
  channels: Channel[];
  erlc_server: Record<string, any>;
  erlc_players: Record<string, any>[];
  modlog_results: Record<string, any>[] | null;
  modlog_user_id: string;
  rank_order: string[];
};
type ToastKind = "success" | "error";
type DashboardToast = {
  id: number;
  kind: ToastKind;
  message: string;
};
type EmbedFieldDraft = {
  id: number;
  name: string;
  value: string;
  inline: boolean;
};
type EmbedDraft = {
  content: string;
  title: string;
  description: string;
  color: string;
  url: string;
  authorName: string;
  authorUrl: string;
  authorIconUrl: string;
  thumbnailUrl: string;
  imageUrl: string;
  footerText: string;
  footerIconUrl: string;
  timestamp: boolean;
};

const DASHBOARD_TOAST_EVENT = "csrp-dashboard-toast";
const DASHBOARD_DATA_REFRESH_EVENT = "csrp-dashboard-refresh";
const DEFAULT_EMBED_DRAFT: EmbedDraft = {
  content: "",
  title: "Announcement",
  description: "Write your embed content here.",
  color: "#5865f2",
  url: "",
  authorName: "",
  authorUrl: "",
  authorIconUrl: "",
  thumbnailUrl: "",
  imageUrl: "",
  footerText: "CSRP Utilities",
  footerIconUrl: "",
  timestamp: false
};

const ACTION_SUCCESS_MESSAGES: Record<string, string> = {
  warn: "User Warned Successfully.",
  kick: "User Kicked Successfully.",
  ban: "User Banned Successfully.",
  unban: "User Unbanned Successfully.",
  mute: "Timeout Applied Successfully.",
  unmute: "Timeout Removed Successfully.",
  infract: "User Infracted Successfully.",
  retire: "Staff Member Retired Successfully.",
  reinstate: "Staff Member Reinstated Successfully.",
  erlc_command: "Command Executed Successfully.",
  partnership: "Partnership Sent Successfully.",
  modlogs_clear_user: "User Modlogs Cleared Successfully.",
  modlogs_clear_all: "All Modlogs Cleared Successfully.",
  embed_send: "Embed Sent Successfully.",
  blacklist_add: "User Blacklisted Successfully.",
  blacklist_remove: "User Removed From Blacklist.",
  docker_exec: "Database Command Executed Successfully.",
  bot_status: "Bot Status Updated Successfully.",
  bot_message: "Bot Message Sent Successfully.",
  settings_save: "Bot Settings Saved Successfully.",
  access_save: "Access Rules Saved Successfully."
};

const navigation = [
  ["overview", "Overview", Gauge],
  ["moderation", "Moderation", ShieldAlert],
  ["staff", "Staff", UserMinus],
  ["erlc", "ERLC", Bot],
  ["partnerships", "Partnerships", Megaphone],
  ["embeds", "Embeds", FileText],
  ["themes", "Themes", Palette],
  ["modlogs", "Modlogs", FileText],
  ["blacklist", "Blacklist", Ban],
  ["docker", "Docker", Database],
  ["updates", "Bot Updates", Send],
  ["settings", "Settings", Settings],
  ["access", "Access", Users]
] as const;

const accessMap: Record<string, string[]> = {
  moderation: ["moderation"],
  staff: ["staff_management", "infractions"],
  erlc: ["erlc"],
  partnerships: ["partnerships"],
  embeds: ["embed_wizard"],
  modlogs: ["modlogs"],
  blacklist: ["command_blacklist"],
  docker: ["docker_commands"],
  updates: ["bot_updates"],
  settings: ["bot_settings"],
  access: ["access_manager"]
};

const DEFAULT_THEME_ID = "csrp-default";
const SELECTED_THEME_STORAGE_KEY = "csrp-dashboard-selected-theme";
const CUSTOM_THEMES_STORAGE_KEY = "csrp-dashboard-custom-themes";
const CUSTOM_THEME_LIMIT = 24;
const DEFAULT_THEME_AUTHOR = "CSRP Utilities";

const THEME_COLOR_FIELDS: { key: keyof ThemeColors; label: string }[] = [
  { key: "background", label: "Background" },
  { key: "backgroundSoft", label: "Soft Background" },
  { key: "panel", label: "Panel" },
  { key: "panelStrong", label: "Raised Panel" },
  { key: "field", label: "Field" },
  { key: "foreground", label: "Text" },
  { key: "muted", label: "Muted Text" },
  { key: "mutedStrong", label: "Strong Muted" },
  { key: "primary", label: "Primary" },
  { key: "primaryStrong", label: "Primary Strong" },
  { key: "primaryInk", label: "Primary Ink" },
  { key: "secondary", label: "Secondary" },
  { key: "highlight", label: "Highlight" },
  { key: "destructive", label: "Destructive" }
];

const MARKETPLACE_THEMES: ThemeDefinition[] = [
  {
    id: DEFAULT_THEME_ID,
    name: "CSRP Default",
    description: "A clean emerald control panel for day-to-day staff work.",
    author: DEFAULT_THEME_AUTHOR,
    tags: ["default", "staff", "green"],
    downloads: 0,
    updated: "5/10/2026",
    rating: 4.8,
    source: "marketplace",
    colors: {
      background: "#090a0a",
      backgroundSoft: "#0f1010",
      panel: "#141514",
      panelStrong: "#191b19",
      field: "#0d0e0e",
      foreground: "#f7f5ef",
      muted: "#a5aaa4",
      mutedStrong: "#c8cdc6",
      primary: "#57d69b",
      primaryStrong: "#32b77d",
      primaryInk: "#06120d",
      secondary: "#9b8cff",
      highlight: "#f4bd5e",
      destructive: "#ef6868"
    }
  },
  {
    id: "midnight-theme",
    name: "Midnight Theme",
    description: "Deep black surfaces with vivid violet actions and soft text.",
    author: DEFAULT_THEME_AUTHOR,
    tags: ["midnight", "purple", "high contrast"],
    downloads: 0,
    updated: "12/23/2024",
    rating: 4.1,
    source: "marketplace",
    colors: {
      background: "#050008",
      backgroundSoft: "#08000f",
      panel: "#0d0314",
      panelStrong: "#160326",
      field: "#07000c",
      foreground: "#f7efff",
      muted: "#9f7abc",
      mutedStrong: "#c9a9e6",
      primary: "#8427f6",
      primaryStrong: "#5f18b7",
      primaryInk: "#080010",
      secondary: "#4b1389",
      highlight: "#f0c85a",
      destructive: "#d73562"
    }
  },
  {
    id: "discord-dark-mode",
    name: "Discord Dark Mode",
    description: "Familiar graphite panels with bright blurple accents.",
    author: DEFAULT_THEME_AUTHOR,
    tags: ["discord", "dark mode", "blue"],
    downloads: 0,
    updated: "1/20/2025",
    rating: 4.1,
    source: "marketplace",
    colors: {
      background: "#1e1f22",
      backgroundSoft: "#25262b",
      panel: "#2b2d31",
      panelStrong: "#313338",
      field: "#1e1f22",
      foreground: "#f2f3f5",
      muted: "#b5bac1",
      mutedStrong: "#dbdee1",
      primary: "#5865f2",
      primaryStrong: "#4752c4",
      primaryInk: "#ffffff",
      secondary: "#3f4147",
      highlight: "#fee75c",
      destructive: "#ed4245"
    }
  },
  {
    id: "crimson-moon",
    name: "Crimson Moon",
    description: "A red command-room theme with warm contrast.",
    author: DEFAULT_THEME_AUTHOR,
    tags: ["discord", "crimson", "red"],
    downloads: 0,
    updated: "1/7/2025",
    rating: 5,
    source: "marketplace",
    colors: {
      background: "#080101",
      backgroundSoft: "#150202",
      panel: "#240505",
      panelStrong: "#430707",
      field: "#120202",
      foreground: "#fff5f2",
      muted: "#d5aaa4",
      mutedStrong: "#f1c9c2",
      primary: "#c23b35",
      primaryStrong: "#7e120f",
      primaryInk: "#fff8f5",
      secondary: "#3f3f3f",
      highlight: "#ffb55f",
      destructive: "#ff1d32"
    }
  },
  {
    id: "civic-blue",
    name: "Civic Blue",
    description: "Calm navy, bright cyan, and tidy operational surfaces.",
    author: DEFAULT_THEME_AUTHOR,
    tags: ["blue", "operations", "clean"],
    downloads: 0,
    updated: "4/18/2026",
    rating: 4.7,
    source: "marketplace",
    colors: {
      background: "#061016",
      backgroundSoft: "#0b1821",
      panel: "#10212b",
      panelStrong: "#142b38",
      field: "#08141c",
      foreground: "#eef9ff",
      muted: "#95afbc",
      mutedStrong: "#bad2dc",
      primary: "#34c6e5",
      primaryStrong: "#1597b5",
      primaryInk: "#031115",
      secondary: "#86b7ff",
      highlight: "#f3cf63",
      destructive: "#ff6c7c"
    }
  },
  {
    id: "ember-terminal",
    name: "Ember Terminal",
    description: "Dark charcoal, amber highlights, and strong danger states.",
    author: DEFAULT_THEME_AUTHOR,
    tags: ["terminal", "amber", "contrast"],
    downloads: 0,
    updated: "2/14/2026",
    rating: 4.5,
    source: "marketplace",
    colors: {
      background: "#0d0c0a",
      backgroundSoft: "#15120e",
      panel: "#1d1812",
      panelStrong: "#272016",
      field: "#100d0a",
      foreground: "#fff7e8",
      muted: "#b9a98e",
      mutedStrong: "#e2cfaa",
      primary: "#f2a93b",
      primaryStrong: "#c2731d",
      primaryInk: "#180d02",
      secondary: "#55c6a1",
      highlight: "#ffe06e",
      destructive: "#f15f4c"
    }
  }
];

const DEFAULT_RAIL_WIDTH = 304;
const MIN_RAIL_WIDTH = 236;
const MAX_RAIL_WIDTH = 440;
const MIN_WORKSPACE_WIDTH = 520;
const RAIL_WIDTH_STORAGE_KEY = "csrp-dashboard-rail-width";

function clampRailWidth(width: number) {
  const viewportMax =
    typeof window === "undefined" ? MAX_RAIL_WIDTH : Math.max(MIN_RAIL_WIDTH, window.innerWidth - MIN_WORKSPACE_WIDTH);
  const maxWidth = Math.min(MAX_RAIL_WIDTH, viewportMax);
  return Math.min(maxWidth, Math.max(MIN_RAIL_WIDTH, Math.round(width)));
}

function hexToRgba(hex: string, alpha: number) {
  const normalized = hex.replace("#", "");
  if (!/^[0-9a-f]{6}$/i.test(normalized)) return `rgba(255, 255, 255, ${alpha})`;
  const value = Number.parseInt(normalized, 16);
  const red = (value >> 16) & 255;
  const green = (value >> 8) & 255;
  const blue = value & 255;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function themeToCssVariables(colors: ThemeColors) {
  return {
    "--bg": colors.background,
    "--bg-soft": colors.backgroundSoft,
    "--panel": colors.panel,
    "--panel-strong": colors.panelStrong,
    "--field": colors.field,
    "--text": colors.foreground,
    "--muted": colors.muted,
    "--muted-strong": colors.mutedStrong,
    "--line": hexToRgba(colors.foreground, 0.13),
    "--line-soft": hexToRgba(colors.foreground, 0.08),
    "--accent": colors.primary,
    "--accent-strong": colors.primaryStrong,
    "--accent-ink": colors.primaryInk,
    "--gold": colors.highlight,
    "--violet": colors.secondary,
    "--danger": colors.destructive
  } as React.CSSProperties & Record<`--${string}`, string>;
}

function isThemeColors(value: unknown): value is ThemeColors {
  if (!value || typeof value !== "object") return false;
  const colors = value as Record<string, unknown>;
  return THEME_COLOR_FIELDS.every(({ key }) => typeof colors[key] === "string" && /^#[0-9a-f]{6}$/i.test(String(colors[key])));
}

function normalizeThemeDefinition(value: unknown, fallbackSource: ThemeDefinition["source"]): ThemeDefinition | null {
  if (!value || typeof value !== "object") return null;
  const payload = value as Partial<ThemeDefinition>;

  if (!payload.id || !isThemeColors(payload.colors)) return null;

  return {
    id: String(payload.id),
    name: String(payload.name || "Untitled Theme"),
    description: String(payload.description || "Custom dashboard theme."),
    author: String(payload.author || "Unknown"),
    tags: Array.isArray(payload.tags) ? payload.tags.map(String).filter(Boolean).slice(0, 8) : ["custom"],
    downloads: Number.isFinite(payload.downloads) ? Number(payload.downloads) : 0,
    updated: String(payload.updated || new Date().toLocaleDateString("en-US")),
    rating: Number.isFinite(payload.rating) ? Number(payload.rating) : 5,
    source: payload.source === "custom" || payload.source === "marketplace" ? payload.source : fallbackSource,
    colors: payload.colors
  };
}

function normalizeImportedTheme(value: unknown): ThemeDefinition | null {
  if (!value || typeof value !== "object") return null;
  const payload = value as Partial<ThemeDefinition>;

  if (!isThemeColors(payload.colors)) return null;

  return {
    id: `custom-${Date.now()}`,
    name: String(payload.name || "Imported Theme"),
    description: String(payload.description || "Imported dashboard theme."),
    author: "You",
    tags: Array.isArray(payload.tags) ? payload.tags.map(String).filter(Boolean).slice(0, 8) : ["imported"],
    downloads: 0,
    updated: new Date().toLocaleDateString("en-US"),
    rating: 5,
    source: "custom",
    colors: payload.colors
  };
}

function readStoredCustomThemes() {
  try {
    const storedThemes = window.localStorage.getItem(CUSTOM_THEMES_STORAGE_KEY);
    const parsed = storedThemes ? JSON.parse(storedThemes) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((theme) => normalizeImportedTheme(theme))
      .filter((theme): theme is ThemeDefinition => Boolean(theme))
      .map((theme, index) => ({
        ...theme,
        id: typeof parsed[index]?.id === "string" ? parsed[index].id : theme.id,
        updated: typeof parsed[index]?.updated === "string" ? parsed[index].updated : theme.updated
      }))
      .slice(0, CUSTOM_THEME_LIMIT);
  } catch {
    return [];
  }
}

function normalizeThemeList(values: unknown, fallbackSource: ThemeDefinition["source"]) {
  if (!Array.isArray(values)) return [];
  return values
    .map((theme) => normalizeThemeDefinition(theme, fallbackSource))
    .filter((theme): theme is ThemeDefinition => Boolean(theme));
}

function mergeThemes(primary: ThemeDefinition[], secondary: ThemeDefinition[]) {
  const themes = new Map<string, ThemeDefinition>();
  [...secondary, ...primary].forEach((theme) => themes.set(theme.id, theme));
  return Array.from(themes.values());
}

function exportTheme(theme: ThemeDefinition) {
  const exportableTheme = {
    name: theme.name,
    description: theme.description,
    author: theme.author,
    tags: theme.tags,
    colors: theme.colors
  };
  const blob = new Blob([JSON.stringify(exportableTheme, null, 2)], { type: "application/json" });
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = `${theme.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "theme"}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

function createDraftFromTheme(theme: ThemeDefinition): ThemeDraft {
  return {
    name: theme.source === "custom" ? theme.name : "",
    description: theme.source === "custom" ? theme.description : "",
    tags: theme.source === "custom" ? theme.tags : [],
    colors: { ...theme.colors }
  };
}

function buildCustomTheme(draft: ThemeDraft): ThemeDefinition {
  return {
    id: `custom-${Date.now()}`,
    name: draft.name.trim() || "Untitled Theme",
    description: draft.description.trim() || "Custom dashboard theme.",
    author: "You",
    tags: draft.tags.length ? draft.tags : ["custom"],
    downloads: 0,
    updated: new Date().toLocaleDateString("en-US"),
    rating: 5,
    source: "custom",
    colors: { ...draft.colors }
  };
}

function emitDashboardToast(kind: ToastKind, message: string) {
  window.dispatchEvent(
    new CustomEvent(DASHBOARD_TOAST_EVENT, {
      detail: { kind, message }
    })
  );
}

function useDashboardData() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    const loadDashboardData = () => {
      const query = window.location.search;
      fetch(`/api/dashboard${query}`, { credentials: "include" })
        .then((response) => {
          if (response.redirected || response.status === 401) {
            window.location.href = "/";
            return null;
          }
          if (!response.ok) throw new Error("Unable to load dashboard data.");
          return response.json();
        })
        .then((payload) => {
          if (!cancelled && payload) {
            setData(payload);
            setError("");
          }
        })
        .catch((err) => {
          if (!cancelled) setError(err.message);
        });
    };

    loadDashboardData();
    window.addEventListener(DASHBOARD_DATA_REFRESH_EVENT, loadDashboardData);
    return () => {
      cancelled = true;
      window.removeEventListener(DASHBOARD_DATA_REFRESH_EVENT, loadDashboardData);
    };
  }, []);

  return { data, error };
}

function fieldValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not set";
  return String(value);
}

function embedFieldsPayload(fields: EmbedFieldDraft[]) {
  return fields
    .filter((field) => field.name.trim() && field.value.trim())
    .map((field) => `${field.name.trim()} | ${field.value.trim().replace(/\n/g, "\\n")} | ${field.inline ? "true" : "false"}`)
    .join("\n");
}

function safeEmbedColor(value: string) {
  return /^#[0-9a-f]{6}$/i.test(value) ? value : "#5865f2";
}

function previewLines(value: string) {
  return value.split("\n").map((line, index) => (
    <span key={index}>
      {line || "\u00a0"}
      {index < value.split("\n").length - 1 && <br />}
    </span>
  ));
}

function roleNames(ids: unknown, roles: Role[]) {
  const selected = Array.isArray(ids) ? ids.map(String) : [];
  return roles.filter((role) => selected.includes(role.id)).map((role) => role.name);
}

type DropdownOption = { id: string; label: string };

function selectedValues(selected: unknown) {
  return Array.isArray(selected) ? selected.map(String) : selected ? [String(selected)] : [];
}

function SelectionDropdown({
  name,
  options,
  selected,
  multiple = false,
  placeholder,
  emptyLabel,
  listLabel
}: {
  name: string;
  options: DropdownOption[];
  selected?: unknown;
  multiple?: boolean;
  placeholder: string;
  emptyLabel?: string;
  listLabel: string;
}) {
  const selectedKey = selectedValues(selected).join("|");
  const [values, setValues] = useState(() => selectedValues(selected));
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setValues(selectedKey ? selectedKey.split("|") : []);
  }, [selectedKey]);

  useEffect(() => {
    if (!open) return;

    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };

    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, [open]);

  const selectedSet = useMemo(() => new Set(values), [values]);
  const selectedOptions = options.filter((option) => selectedSet.has(option.id));
  const summary = selectedOptions.length
    ? multiple
      ? selectedOptions.map((option) => option.label).join(", ")
      : selectedOptions[0].label
    : placeholder;

  const toggleValue = (value: string) => {
    setValues((current) => {
      if (!multiple) {
        setOpen(false);
        return value ? [value] : [];
      }

      return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
    });
  };

  return (
    <div className={`dropdown-select ${open ? "open" : ""}`} ref={rootRef} onKeyDown={(event) => event.key === "Escape" && setOpen(false)}>
      {multiple ? (
        values.map((value) => <input key={value} type="hidden" name={name} value={value} />)
      ) : (
        <input type="hidden" name={name} value={values[0] ?? ""} />
      )}
      <button
        className="dropdown-trigger"
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((isOpen) => !isOpen)}
      >
        <span className={selectedOptions.length ? "" : "placeholder"}>{summary}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {open && (
        <div className="dropdown-panel" role="listbox" aria-multiselectable={multiple || undefined}>
          <div className="dropdown-panel-label">{listLabel}</div>
          {!multiple && emptyLabel && (
            <button
              className={`dropdown-option ${values.length === 0 ? "selected" : ""}`}
              type="button"
              role="option"
              aria-selected={values.length === 0}
              onClick={() => toggleValue("")}
            >
              <span>{emptyLabel}</span>
              {values.length === 0 && <Check size={15} aria-hidden="true" />}
            </button>
          )}
          {options.map((option) => {
            const isSelected = selectedSet.has(option.id);
            return (
              <button
                className={`dropdown-option ${isSelected ? "selected" : ""}`}
                key={option.id}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => toggleValue(option.id)}
              >
                <span>{option.label}</span>
                {isSelected && <Check size={15} aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function RoleSelect({ name, roles, selected, multiple = true }: { name: string; roles: Role[]; selected?: unknown; multiple?: boolean }) {
  return (
    <SelectionDropdown
      name={name}
      options={roles.map((role) => ({ id: role.id, label: role.name }))}
      selected={selected}
      multiple={multiple}
      placeholder={multiple ? "Select roles" : "No role selected"}
      emptyLabel="No role selected"
      listLabel="Roles"
    />
  );
}

function ChannelSelect({ name, channels, selected }: { name: string; channels: Channel[]; selected?: unknown }) {
  return (
    <SelectionDropdown
      name={name}
      options={channels.map((channel) => ({ id: channel.id, label: `#${channel.name}` }))}
      selected={selected}
      placeholder="No channel selected"
      emptyLabel="No channel selected"
      listLabel="Channels"
    />
  );
}

function DashboardPostForm({
  action,
  children,
  className
}: {
  action: string;
  children: React.ReactNode;
  className: string;
}) {
  const [submitting, setSubmitting] = useState(false);

  const submitAction = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    const form = event.currentTarget;
    setSubmitting(true);

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "include",
        headers: {
          Accept: "application/json",
          "X-Requested-With": "fetch"
        }
      });
      const contentType = response.headers.get("content-type") || "";
      const payload = contentType.includes("application/json") ? await response.json() : null;

      if (response.redirected || response.status === 401) {
        window.location.href = "/";
        return;
      }

      if (!response.ok || payload?.ok === false) {
        throw new Error(payload?.error || payload?.message || "Action failed.");
      }

      emitDashboardToast("success", ACTION_SUCCESS_MESSAGES[action] || payload?.message || "Action Completed Successfully.");
      window.dispatchEvent(new Event(DASHBOARD_DATA_REFRESH_EVENT));
    } catch (err) {
      emitDashboardToast("error", err instanceof Error ? err.message : "Action failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className={className} method="post" action={`/api/actions/${action}`} onSubmit={submitAction} aria-busy={submitting}>
      {children}
    </form>
  );
}

function ActionForm({ action, children, danger = false }: { action: string; children: React.ReactNode; danger?: boolean }) {
  return (
    <DashboardPostForm action={action} className={`setting-card form-grid ${danger ? "danger-card" : ""}`}>
      {children}
    </DashboardPostForm>
  );
}

function ToastViewport() {
  const [toasts, setToasts] = useState<DashboardToast[]>([]);

  useEffect(() => {
    const timers = new Map<number, number>();

    const dismiss = (id: number) => {
      window.clearTimeout(timers.get(id));
      timers.delete(id);
      setToasts((current) => current.filter((toast) => toast.id !== id));
    };

    const showToast = (event: Event) => {
      const detail = (event as CustomEvent<{ kind: ToastKind; message: string }>).detail;
      const id = Date.now() + Math.floor(Math.random() * 1000);
      const toast = {
        id,
        kind: detail?.kind || "success",
        message: detail?.message || "Action Completed Successfully."
      };

      setToasts((current) => [...current.slice(-3), toast]);
      timers.set(id, window.setTimeout(() => dismiss(id), 4200));
    };

    window.addEventListener(DASHBOARD_TOAST_EVENT, showToast);
    return () => {
      window.removeEventListener(DASHBOARD_TOAST_EVENT, showToast);
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  if (!toasts.length) return null;

  return (
    <div className="toast-stack" aria-live="polite" aria-label="Dashboard notifications">
      {toasts.map((toast) => (
        <div className={`toast ${toast.kind}`} key={toast.id} role={toast.kind === "error" ? "alert" : "status"}>
          {toast.kind === "success" ? <Check size={18} /> : <X size={18} />}
          <span>{toast.message}</span>
          <button type="button" aria-label="Dismiss notification" onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}>
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const { data, error } = useDashboardData();
  const [active, setActive] = useState("overview");
  const [railWidth, setRailWidth] = useState(DEFAULT_RAIL_WIDTH);
  const [railWasResized, setRailWasResized] = useState(false);
  const [selectedThemeId, setSelectedThemeId] = useState(DEFAULT_THEME_ID);
  const [marketplaceThemes, setMarketplaceThemes] = useState<ThemeDefinition[]>(MARKETPLACE_THEMES);
  const [customThemes, setCustomThemes] = useState<ThemeDefinition[]>([]);
  const [themesHydrated, setThemesHydrated] = useState(false);
  const [themeError, setThemeError] = useState("");
  const railNameRef = useRef<HTMLElement>(null);
  const memberNameRef = useRef<HTMLElement>(null);

  const visibleNav = useMemo(() => {
    if (!data) return navigation.slice(0, 1);
    return navigation.filter(([id]) => id === "overview" || id === "themes" || accessMap[id]?.some((key) => data.feature_access[key]));
  }, [data]);

  const allThemes = useMemo(() => [...marketplaceThemes, ...customThemes], [marketplaceThemes, customThemes]);
  const activeTheme = allThemes.find((theme) => theme.id === selectedThemeId) ?? marketplaceThemes[0] ?? MARKETPLACE_THEMES[0];

  useEffect(() => {
    const storedWidth = Number.parseInt(window.localStorage.getItem(RAIL_WIDTH_STORAGE_KEY) || "", 10);
    if (!Number.isNaN(storedWidth)) {
      setRailWidth(clampRailWidth(storedWidth));
      setRailWasResized(true);
    }
  }, []);

  useEffect(() => {
    if (!data || railWasResized) return;
    const longestName = Math.max(railNameRef.current?.scrollWidth || 0, memberNameRef.current?.scrollWidth || 0);
    if (longestName > 0) {
      setRailWidth((current) => Math.max(current, clampRailWidth(longestName + 116)));
    }
  }, [data, railWasResized]);

  useEffect(() => {
    let cancelled = false;

    const loadThemes = async () => {
      const storedThemeId = window.localStorage.getItem(SELECTED_THEME_STORAGE_KEY) || DEFAULT_THEME_ID;

      try {
        const response = await fetch("/api/themes", { credentials: "include" });
        if (response.redirected || response.status === 401) {
          window.location.href = "/";
          return;
        }
        if (!response.ok) throw new Error("Unable to load dashboard themes.");

        const payload = (await response.json()) as ThemeCatalogResponse;
        let marketplace = normalizeThemeList(payload.marketplace, "marketplace");
        let mine = normalizeThemeList(payload.mine, "custom");
        const storedCustomThemes = readStoredCustomThemes();

        if (storedCustomThemes.length) {
          const existingIds = new Set([...marketplace, ...mine].map((theme) => theme.id));
          const migratedThemes = await Promise.all(
            storedCustomThemes
              .filter((theme) => !existingIds.has(theme.id))
              .map(async (theme) => {
                const migrateResponse = await fetch("/api/themes", {
                  method: "POST",
                  credentials: "include",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(theme)
                });
                if (!migrateResponse.ok) return null;
                const migratePayload = await migrateResponse.json();
                return normalizeThemeDefinition(migratePayload.theme, "custom");
              })
          );
          const savedThemes = migratedThemes.filter((theme): theme is ThemeDefinition => Boolean(theme));
          if (savedThemes.length) {
            mine = mergeThemes(savedThemes, mine);
            marketplace = mergeThemes(savedThemes.map((theme) => ({ ...theme, source: "marketplace" as const })), marketplace);
            window.localStorage.removeItem(CUSTOM_THEMES_STORAGE_KEY);
          }
        }

        if (cancelled) return;
        setMarketplaceThemes(marketplace.length ? marketplace : MARKETPLACE_THEMES);
        setCustomThemes(mine);
        setThemeError("");
      } catch (err) {
        if (cancelled) return;
        setMarketplaceThemes(MARKETPLACE_THEMES);
        setCustomThemes(readStoredCustomThemes());
        setThemeError(err instanceof Error ? err.message : "Unable to load dashboard themes.");
      } finally {
        if (!cancelled) {
          setSelectedThemeId(storedThemeId);
          setThemesHydrated(true);
        }
      }
    };

    loadThemes();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!themesHydrated) return;
    window.localStorage.setItem(SELECTED_THEME_STORAGE_KEY, activeTheme.id);
  }, [activeTheme.id, themesHydrated]);

  if (error) {
    return <main className="state-page"><p>{error}</p></main>;
  }

  if (!data) {
    return <main className="state-page"><RefreshCw className="spin" /><p>Loading dashboard...</p></main>;
  }

  const can = (key: string) => Boolean(data.feature_access[key]);
  const activeLabel = visibleNav.find(([id]) => id === active)?.[1] ?? "Dashboard";
  const shellStyle = {
    "--rail-width": `${railWidth}px`,
    ...themeToCssVariables(activeTheme.colors)
  } as React.CSSProperties & Record<`--${string}`, string>;

  const persistRailWidth = (width: number) => {
    const nextWidth = clampRailWidth(width);
    window.localStorage.setItem(RAIL_WIDTH_STORAGE_KEY, String(nextWidth));
    return nextWidth;
  };

  const saveCustomTheme = async (theme: ThemeDefinition) => {
    try {
      const response = await fetch("/api/themes", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(theme)
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || "Unable to save theme.");
      }

      const payload = await response.json();
      const savedTheme = normalizeThemeDefinition(payload.theme, "custom");
      if (!savedTheme) throw new Error("The theme API returned an invalid theme.");

      setCustomThemes((themes) => mergeThemes([savedTheme], themes).slice(0, CUSTOM_THEME_LIMIT));
      setMarketplaceThemes((themes) => mergeThemes([{ ...savedTheme, source: "marketplace" as const }], themes));
      setSelectedThemeId(savedTheme.id);
      setThemeError("");
      return true;
    } catch (err) {
      setThemeError(err instanceof Error ? err.message : "Unable to save theme.");
      return false;
    }
  };

  const duplicateTheme = (theme: ThemeDefinition) => {
    void saveCustomTheme({
      ...theme,
      id: `custom-${Date.now()}`,
      name: `${theme.name} Copy`,
      author: "You",
      source: "custom",
      downloads: 0,
      updated: new Date().toLocaleDateString("en-US")
    });
  };

  const installMarketplaceTheme = async (theme: ThemeDefinition) => {
    try {
      const response = await fetch(`/api/themes/${encodeURIComponent(theme.id)}/install`, {
        method: "POST",
        credentials: "include"
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || "Unable to install theme.");
      }

      const payload = await response.json();
      const mine = normalizeThemeList(payload.mine, "custom");
      const installedTheme = normalizeThemeDefinition(payload.theme, "custom");

      if (mine.length) setCustomThemes(mine);
      if (installedTheme) {
        setMarketplaceThemes((themes) =>
          themes.map((item) => (item.id === installedTheme.id ? { ...installedTheme, source: "marketplace" as const } : item))
        );
        setSelectedThemeId(installedTheme.id);
      } else {
        setSelectedThemeId(theme.id);
      }
      setThemeError("");
    } catch (err) {
      setThemeError(err instanceof Error ? err.message : "Unable to install theme.");
    }
  };

  const deleteCustomTheme = async (themeId: string) => {
    try {
      const response = await fetch(`/api/themes/${encodeURIComponent(themeId)}/install`, {
        method: "DELETE",
        credentials: "include"
      });
      if (!response.ok) throw new Error("Unable to remove theme.");
      const payload = await response.json();
      const mine = normalizeThemeList(payload.mine, "custom");
      setCustomThemes(mine);
      if (payload.deleted) setMarketplaceThemes((themes) => themes.filter((theme) => theme.id !== themeId));
      setThemeError("");
    } catch (err) {
      setCustomThemes((themes) => themes.filter((theme) => theme.id !== themeId));
      setThemeError(err instanceof Error ? err.message : "Unable to remove theme.");
    }
    if (selectedThemeId === themeId) setSelectedThemeId(DEFAULT_THEME_ID);
  };

  const startRailResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    setRailWasResized(true);

    const startX = event.clientX;
    const startWidth = railWidth;

    document.body.classList.add("is-resizing-rail");

    const handlePointerMove = (moveEvent: PointerEvent) => {
      setRailWidth(clampRailWidth(startWidth + moveEvent.clientX - startX));
    };

    const stopResizing = () => {
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", stopResizing);
      document.removeEventListener("pointercancel", stopResizing);
      document.body.classList.remove("is-resizing-rail");
      setRailWidth((width) => persistRailWidth(width));
    };

    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", stopResizing);
    document.addEventListener("pointercancel", stopResizing);
  };

  const handleRailResizeKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    let nextWidth: number | null = null;

    if (event.key === "ArrowLeft") nextWidth = railWidth - 16;
    if (event.key === "ArrowRight") nextWidth = railWidth + 16;
    if (event.key === "Home") nextWidth = MIN_RAIL_WIDTH;
    if (event.key === "End") nextWidth = MAX_RAIL_WIDTH;

    if (nextWidth === null) return;

    event.preventDefault();
    setRailWasResized(true);
    setRailWidth(persistRailWidth(nextWidth));
  };

  return (
    <main className="app-shell" style={shellStyle}>
      <ToastViewport />
      <aside className="rail" aria-label="Dashboard navigation">
        <a className="rail-brand" href="/dashboard" aria-label={`${data.guild.name} dashboard`}>
          <div className="guild-badge">{data.guild.icon_url ? <img src={data.guild.icon_url} alt="" /> : data.guild.name.slice(0, 2)}</div>
          <div>
            <strong ref={railNameRef}>{data.guild.name}</strong>
            <span>Control Panel</span>
          </div>
        </a>
        <nav aria-label="Dashboard sections">
          {visibleNav.map(([id, label, Icon]) => (
            <button key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)} title={label} aria-label={label}>
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="rail-footer">
          <img src={data.member.avatar_url} alt="" />
          <div>
            <strong ref={memberNameRef}>{data.member.display_name}</strong>
            <span>Signed in</span>
          </div>
          <a className="logout-button" href="/api/logout" title="Logout" aria-label="Logout"><LogOut size={18} /><span>Logout</span></a>
        </div>
        <div
          className="rail-resizer"
          role="separator"
          aria-label="Resize sidebar"
          aria-orientation="vertical"
          aria-valuemin={MIN_RAIL_WIDTH}
          aria-valuemax={MAX_RAIL_WIDTH}
          aria-valuenow={railWidth}
          tabIndex={0}
          title="Drag to resize"
          onPointerDown={startRailResize}
          onKeyDown={handleRailResizeKeyDown}
        />
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-copy">
            <div className="crumbs">
              <span>Home</span><span>/</span><span>{data.guild.name}</span><span>/</span><strong>Dashboard</strong>
            </div>
            <h1>{activeLabel}</h1>
          </div>
          <div className="top-actions">
            <button className="button ghost" onClick={() => window.location.reload()}><RefreshCw size={16} />Refresh</button>
            <button className="button ghost" onClick={() => setActive("settings")} disabled={!can("bot_settings")}><SlidersHorizontal size={16} />Settings</button>
          </div>
        </header>

        <div className="section-tabs">
          {visibleNav.map(([id, label]) => (
            <button key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)}>{label}</button>
          ))}
        </div>

        <div className="content-grid">
          {active === "overview" && <Overview data={data} />}
          {active === "moderation" && <Moderation can={can} />}
          {active === "staff" && <Staff can={can} />}
          {active === "erlc" && <Erlc data={data} />}
          {active === "partnerships" && <Partnerships channels={data.channels} />}
          {active === "embeds" && <Embeds channels={data.channels} />}
          {active === "themes" && (
            <Themes
              selectedThemeId={activeTheme.id}
              activeTheme={activeTheme}
              marketplaceThemes={marketplaceThemes}
              customThemes={customThemes}
              themeError={themeError}
              onApplyTheme={setSelectedThemeId}
              onDeleteTheme={deleteCustomTheme}
              onDuplicateTheme={duplicateTheme}
              onInstallTheme={installMarketplaceTheme}
              onSaveTheme={saveCustomTheme}
            />
          )}
          {active === "modlogs" && <Modlogs data={data} />}
          {active === "blacklist" && <Blacklist />}
          {active === "docker" && <Docker />}
          {active === "updates" && <BotUpdates channels={data.channels} />}
          {active === "settings" && <BotSettings data={data} />}
          {active === "access" && <AccessManager data={data} />}
        </div>
      </section>
    </main>
  );
}

function Themes({
  selectedThemeId,
  activeTheme,
  marketplaceThemes: catalogThemes,
  customThemes,
  themeError,
  onApplyTheme,
  onDeleteTheme,
  onDuplicateTheme,
  onInstallTheme,
  onSaveTheme
}: {
  selectedThemeId: string;
  activeTheme: ThemeDefinition;
  marketplaceThemes: ThemeDefinition[];
  customThemes: ThemeDefinition[];
  themeError: string;
  onApplyTheme: (themeId: string) => void;
  onDeleteTheme: (themeId: string) => Promise<void>;
  onDuplicateTheme: (theme: ThemeDefinition) => void;
  onInstallTheme: (theme: ThemeDefinition) => Promise<void>;
  onSaveTheme: (theme: ThemeDefinition) => Promise<boolean>;
}) {
  const [view, setView] = useState<"marketplace" | "create" | "mine">("marketplace");
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState<"latest" | "popular">("latest");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const installedThemeIds = useMemo(() => new Set([DEFAULT_THEME_ID, ...customThemes.map((theme) => theme.id)]), [customThemes]);

  const allMarketplaceTags = useMemo(
    () => Array.from(new Set(catalogThemes.flatMap((theme) => theme.tags))).sort((a, b) => a.localeCompare(b)),
    [catalogThemes]
  );

  const filteredMarketplaceThemes = useMemo(() => {
    const loweredQuery = query.trim().toLowerCase();
    return catalogThemes.filter((theme) => {
      const matchesQuery =
        !loweredQuery ||
        [theme.name, theme.description, theme.author, ...theme.tags].some((value) => value.toLowerCase().includes(loweredQuery));
      const matchesTags = selectedTags.every((tag) => theme.tags.includes(tag));
      return matchesQuery && matchesTags;
    }).sort((left, right) => {
      if (sortMode === "popular") return right.downloads - left.downloads || right.rating - left.rating;
      return Date.parse(right.updated) - Date.parse(left.updated);
    });
  }, [catalogThemes, query, selectedTags, sortMode]);

  const toggleTag = (tag: string) => {
    setSelectedTags((tags) => (tags.includes(tag) ? tags.filter((item) => item !== tag) : [...tags, tag]));
  };

  const handleSaveTheme = async (theme: ThemeDefinition) => {
    const saved = await onSaveTheme(theme);
    if (saved) setView("mine");
    return saved;
  };

  return (
    <section className="themes-shell">
      <div className="theme-header">
        <div className="page-title">
          <p>Themes</p>
          <h1>{view === "create" ? "Create Theme" : view === "mine" ? "My Themes" : "Theme Marketplace"}</h1>
          <span>{view === "create" ? "Design a custom dashboard look." : "Discover, apply, and manage dashboard themes."}</span>
        </div>
        <div className="theme-view-actions" role="tablist" aria-label="Theme views">
          <button className={`button ghost ${view === "marketplace" ? "active" : ""}`} onClick={() => setView("marketplace")}>
            Marketplace
          </button>
          <button className={`button ghost ${view === "mine" ? "active" : ""}`} onClick={() => setView("mine")}>
            My Themes
          </button>
          <button className={`button primary ${view === "create" ? "active" : ""}`} onClick={() => setView("create")}>
            <Plus size={16} />
            Create Theme
          </button>
        </div>
      </div>

      {themeError && <div className="theme-alert">{themeError}</div>}

      {view === "marketplace" && (
        <>
          <div className="theme-market-toolbar">
            <label className="theme-search">
              <Search size={18} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search themes" />
            </label>
            <div className="theme-toolbar-actions">
              <button className="button ghost" onClick={() => setFiltersOpen((open) => !open)}>
                <Filter size={16} />
                Filters ({selectedTags.length})
              </button>
              <div className="segmented-control" aria-label="Theme sort">
                <button className={sortMode === "latest" ? "active" : ""} onClick={() => setSortMode("latest")}>
                  Latest
                </button>
                <button className={sortMode === "popular" ? "active" : ""} onClick={() => setSortMode("popular")}>
                  Popular
                </button>
              </div>
            </div>
          </div>

          {filtersOpen && (
            <div className="theme-filter-panel">
              {allMarketplaceTags.map((tag) => (
                <button key={tag} className={selectedTags.includes(tag) ? "active" : ""} onClick={() => toggleTag(tag)}>
                  {tag}
                </button>
              ))}
              {selectedTags.length > 0 && (
                <button className="clear-filter" onClick={() => setSelectedTags([])}>
                  Clear
                </button>
              )}
            </div>
          )}

          <div className="theme-grid">
            {filteredMarketplaceThemes.map((theme) => {
              const installed = installedThemeIds.has(theme.id);
              return (
                <ThemeCard
                  key={theme.id}
                  theme={theme}
                  selected={selectedThemeId === theme.id}
                  primaryAction={installed ? "Apply" : "Install"}
                  onApply={() => (installed ? onApplyTheme(theme.id) : void onInstallTheme(theme))}
                  onDuplicate={() => onDuplicateTheme(theme)}
                />
              );
            })}
          </div>
        </>
      )}

      {view === "create" && (
        <ThemeCreator
          baseTheme={activeTheme}
          onBack={() => setView("marketplace")}
          onImportTheme={handleSaveTheme}
          onSaveTheme={handleSaveTheme}
        />
      )}

      {view === "mine" && (
        <MyThemes
          customThemes={customThemes}
          selectedThemeId={selectedThemeId}
          onApplyTheme={onApplyTheme}
          onCreateTheme={() => setView("create")}
          onDeleteTheme={onDeleteTheme}
          onDuplicateTheme={onDuplicateTheme}
        />
      )}
    </section>
  );
}

function ThemeCard({
  theme,
  selected,
  primaryAction = "Apply",
  onApply,
  onDelete,
  onDuplicate
}: {
  theme: ThemeDefinition;
  selected: boolean;
  primaryAction?: "Apply" | "Install";
  onApply: () => void;
  onDelete?: () => void;
  onDuplicate: () => void;
}) {
  const PrimaryIcon = selected ? Check : primaryAction === "Install" ? Download : Palette;

  return (
    <article className={`theme-card ${selected ? "selected" : ""}`}>
      <ThemePreview theme={theme} />
      <div className="theme-card-body">
        <div>
          <h2>{theme.name}</h2>
          <p>Created by {theme.author}</p>
        </div>
        <span className="theme-rating">
          <Star size={14} fill="currentColor" />
          {theme.rating.toFixed(1)}
        </span>
      </div>
      <div className="theme-tags">
        {theme.tags.slice(0, 3).map((tag) => (
          <span key={tag}>{tag}</span>
        ))}
      </div>
      <div className="theme-meta">
        <span>
          <Download size={14} />
          {theme.downloads}
        </span>
        <span>Updated {theme.updated}</span>
      </div>
      <div className="theme-card-actions">
        <button className={`button ${selected ? "ghost" : "primary"}`} onClick={onApply}>
          <PrimaryIcon size={16} />
          {selected ? "Applied" : primaryAction}
        </button>
        <button className="icon-button" title="Duplicate theme" aria-label={`Duplicate ${theme.name}`} onClick={onDuplicate}>
          <Copy size={16} />
        </button>
        <button className="icon-button" title="Export theme" aria-label={`Export ${theme.name}`} onClick={() => exportTheme(theme)}>
          <Download size={16} />
        </button>
        {onDelete && (
          <button className="icon-button danger" title="Delete theme" aria-label={`Delete ${theme.name}`} onClick={onDelete}>
            <Trash2 size={16} />
          </button>
        )}
      </div>
    </article>
  );
}

function ThemePreview({ theme }: { theme: ThemeDefinition }) {
  const previewStyle = themeToCssVariables(theme.colors);

  return (
    <div className="theme-preview" style={previewStyle}>
      <div className="theme-preview-surface">
        <h3>{theme.name || "Theme Preview"}</h3>
        <p>{theme.description || "This is how dashboard content looks in a card."}</p>
        <div className="theme-preview-buttons">
          <span className="primary">Primary</span>
          <span className="secondary">Secondary</span>
          <span className="danger">Destructive</span>
        </div>
      </div>
    </div>
  );
}

function ThemeCreator({
  baseTheme,
  onBack,
  onImportTheme,
  onSaveTheme
}: {
  baseTheme: ThemeDefinition;
  onBack: () => void;
  onImportTheme: (theme: ThemeDefinition) => Promise<boolean>;
  onSaveTheme: (theme: ThemeDefinition) => Promise<boolean>;
}) {
  const initialDraft = useMemo(() => createDraftFromTheme(baseTheme), [baseTheme]);
  const [draft, setDraft] = useState<ThemeDraft>(initialDraft);
  const [history, setHistory] = useState<ThemeDraft[]>([initialDraft]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [tagValue, setTagValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);

  const previewTheme = useMemo<ThemeDefinition>(
    () => ({
      id: "theme-preview",
      name: draft.name || "Custom Theme",
      description: draft.description || "This is how dashboard content looks in a card.",
      author: "You",
      tags: draft.tags,
      downloads: 0,
      updated: "Live",
      rating: 5,
      source: "custom",
      colors: draft.colors
    }),
    [draft]
  );

  const commitDraft = (nextDraft: ThemeDraft) => {
    setDraft(nextDraft);
    setHistory((entries) => {
      const nextHistory = [...entries.slice(0, historyIndex + 1), nextDraft].slice(-40);
      setHistoryIndex(nextHistory.length - 1);
      return nextHistory;
    });
  };

  const updateDraft = (patch: Partial<ThemeDraft>) => {
    commitDraft({ ...draft, ...patch });
  };

  const updateColor = (key: keyof ThemeColors, value: string) => {
    commitDraft({ ...draft, colors: { ...draft.colors, [key]: value } });
  };

  const undo = () => {
    const nextIndex = Math.max(0, historyIndex - 1);
    setHistoryIndex(nextIndex);
    setDraft(history[nextIndex]);
  };

  const redo = () => {
    const nextIndex = Math.min(history.length - 1, historyIndex + 1);
    setHistoryIndex(nextIndex);
    setDraft(history[nextIndex]);
  };

  const addTag = () => {
    const nextTag = tagValue.trim().toLowerCase();
    if (!nextTag || draft.tags.includes(nextTag)) return;
    commitDraft({ ...draft, tags: [...draft.tags, nextTag].slice(0, 8) });
    setTagValue("");
  };

  const removeTag = (tag: string) => {
    commitDraft({ ...draft, tags: draft.tags.filter((item) => item !== tag) });
  };

  const importThemeFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const importedTheme = normalizeImportedTheme(JSON.parse(String(reader.result)));
        if (!importedTheme) return;
        commitDraft(createDraftFromTheme(importedTheme));
        void onImportTheme(importedTheme);
      } catch {
        return;
      } finally {
        event.target.value = "";
      }
    };
    reader.readAsText(file);
  };

  const saveTheme = async () => {
    setIsSaving(true);
    try {
      await onSaveTheme(buildCustomTheme(draft));
    } finally {
      setIsSaving(false);
    }
  };

  const resetToBase = () => {
    commitDraft({ ...draft, colors: { ...baseTheme.colors } });
  };

  return (
    <div className="theme-create-layout">
      <div className="theme-create-toolbar">
        <button className="button ghost" onClick={onBack}>
          Marketplace
        </button>
        <div>
          <button className="button ghost" onClick={undo} disabled={historyIndex === 0}>
            <Undo2 size={16} />
            Undo
          </button>
          <button className="button ghost" onClick={redo} disabled={historyIndex === history.length - 1}>
            <Redo2 size={16} />
            Redo
          </button>
          <button className="button ghost" onClick={() => exportTheme(buildCustomTheme(draft))}>
            <Download size={16} />
            Export
          </button>
          <button className="button ghost" onClick={() => importRef.current?.click()}>
            <Upload size={16} />
            Import
          </button>
          <button className="button primary" onClick={saveTheme} disabled={isSaving}>
            <Save size={16} />
            {isSaving ? "Saving..." : "Save Theme"}
          </button>
        </div>
        <input ref={importRef} className="hidden-file-input" type="file" accept="application/json,.json" onChange={importThemeFile} />
      </div>

      <div className="theme-builder-grid">
        <div className="theme-builder-panels">
          <section className="setting-card theme-form-panel">
            <h2>Theme Information</h2>
            <label>
              Theme Name
              <input value={draft.name} onChange={(event) => updateDraft({ name: event.target.value })} placeholder="Theme name" />
            </label>
            <label>
              Description
              <textarea value={draft.description} onChange={(event) => updateDraft({ description: event.target.value })} placeholder="Short description" />
            </label>
            <label>
              Tags
              <div className="tag-input-row">
                <input
                  value={tagValue}
                  onChange={(event) => setTagValue(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addTag();
                    }
                  }}
                  placeholder="Tag name"
                />
                <button className="icon-button" aria-label="Add tag" onClick={addTag}>
                  <Plus size={16} />
                </button>
              </div>
            </label>
            <div className="theme-tags editable">
              {draft.tags.map((tag) => (
                <button key={tag} onClick={() => removeTag(tag)}>
                  {tag}
                  <X size={13} />
                </button>
              ))}
            </div>
          </section>

          <section className="setting-card theme-form-panel">
            <div className="panel-title-row">
              <h2>Color Configuration</h2>
              <button className="button ghost" onClick={resetToBase}>
                Use Applied Theme
              </button>
            </div>
            <div className="color-config-grid">
              {THEME_COLOR_FIELDS.map(({ key, label }) => (
                <label key={key} className="color-config-row">
                  <span>{label}</span>
                  <input type="color" value={draft.colors[key]} onChange={(event) => updateColor(key, event.target.value)} />
                  <input
                    value={draft.colors[key]}
                    onChange={(event) => {
                      const value = event.target.value.trim();
                      if (/^#[0-9a-f]{6}$/i.test(value)) updateColor(key, value);
                    }}
                    aria-label={`${label} hex value`}
                  />
                </label>
              ))}
            </div>
          </section>
        </div>

        <section className="setting-card theme-live-preview">
          <h2>Live Preview</h2>
          <ThemePreview theme={previewTheme} />
          <div className="preview-form-block" style={themeToCssVariables(draft.colors)}>
            <h3>Form Elements</h3>
            <input placeholder="Input field" />
            <div className="theme-preview-buttons">
              <button>Cancel</button>
              <button className="primary">Submit</button>
            </div>
          </div>
          <div className="preview-tabs" style={themeToCssVariables(draft.colors)}>
            <div>
              <button className="active">Account</button>
              <button>Password</button>
            </div>
            <p>Account settings content</p>
            <div className="theme-preview-buttons">
              <span className="primary">Default</span>
              <span className="secondary">Secondary</span>
              <span className="danger">Destructive</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function MyThemes({
  customThemes,
  selectedThemeId,
  onApplyTheme,
  onCreateTheme,
  onDeleteTheme,
  onDuplicateTheme
}: {
  customThemes: ThemeDefinition[];
  selectedThemeId: string;
  onApplyTheme: (themeId: string) => void;
  onCreateTheme: () => void;
  onDeleteTheme: (themeId: string) => Promise<void>;
  onDuplicateTheme: (theme: ThemeDefinition) => void;
}) {
  if (!customThemes.length) {
    return (
      <section className="empty-themes setting-card">
        <Palette size={28} />
        <h2>No custom themes yet</h2>
        <p>Create a theme or duplicate a marketplace theme to build your collection.</p>
        <button className="button primary" onClick={onCreateTheme}>
          <Plus size={16} />
          Create Theme
        </button>
      </section>
    );
  }

  return (
    <div className="theme-grid">
      {customThemes.map((theme) => (
        <ThemeCard
          key={theme.id}
          theme={theme}
          selected={selectedThemeId === theme.id}
          onApply={() => onApplyTheme(theme.id)}
          onDuplicate={() => onDuplicateTheme(theme)}
          onDelete={
            theme.id === DEFAULT_THEME_ID
              ? undefined
              : () => {
                  if (window.confirm(`Delete ${theme.name}?`)) void onDeleteTheme(theme.id);
                }
          }
        />
      ))}
    </div>
  );
}

function Overview({ data }: { data: DashboardData }) {
  const stats = [
    ["Members", data.stats.member_count],
    ["Roles", data.stats.role_count],
    ["Channels", data.stats.channel_count],
    ["Modlogs", data.stats.modlog_count],
    ["Retirements", data.stats.retirement_count],
    ["ERLC Players", data.stats.erlc_player_count],
    ["Command Blacklists", data.stats.command_blacklist_count],
  ];

  return (
    <>
      <section className="dashboard-hero">
        <div className="page-title">
          <p>CSRP Utilities</p>
          <h1>Dashboard</h1>
          <span>{data.member.display_name} in {data.guild.name}</span>
        </div>
        <div className="hero-summary">
          <span>Bot latency</span>
          <strong>{data.stats.bot_latency_ms}ms</strong>
        </div>
      </section>
      <section className="stats-row">
        {stats.map(([label, value]) => <article key={label} className="stat-card"><span>{label}</span><strong>{value}</strong></article>)}
      </section>
      <section className="settings-layout">
        <nav className="section-index">
          <strong>Configuration Snapshot</strong>
          <span>Staff Roles</span><span>Channels</span><span>Rank Roles</span>
        </nav>
        <div className="card-stack">
          <article className="setting-card">
            <h2>Staff Roles</h2>
            <p>Current configured staff roles shown by name.</p>
            <div className="pill-row">{(data.readable_settings.staff_roles || []).map((name: string) => <span key={name}>{name}</span>)}</div>
          </article>
          <article className="setting-card">
            <h2>Channels</h2>
            <p>Retirement log: {fieldValue(data.readable_settings.retirement_log_channel)}</p>
            <p>Feedback channel: {fieldValue(data.readable_settings.staff_feedback_channel)}</p>
          </article>
        </div>
      </section>
    </>
  );
}

function Moderation({ can }: { can: (key: string) => boolean }) {
  return (
    <Panel title="Moderation" index={["Warn", "Kick / Ban", "Timeouts"]}>
      {can("moderation") && (
        <div className="two-col">
          {["warn", "kick", "ban", "unban"].map((action) => (
            <ActionForm action={action} key={action}>
              <h2>{action[0].toUpperCase() + action.slice(1)} User</h2>
              <input name="target_id" placeholder="User ID or username" required />
              <textarea name="reason" placeholder="Reason" required />
              <button className="button primary">Submit</button>
            </ActionForm>
          ))}
          <ActionForm action="mute"><h2>Apply Timeout</h2><input name="target_id" placeholder="User ID or username" required /><input name="duration" placeholder="10m / 2h / 1d" required /><textarea name="reason" placeholder="Reason" required /><button className="button primary">Apply Timeout</button></ActionForm>
          <ActionForm action="unmute"><h2>Remove Timeout</h2><input name="target_id" placeholder="User ID or username" required /><textarea name="reason" placeholder="Reason" required /><button className="button primary">Remove Timeout</button></ActionForm>
        </div>
      )}
    </Panel>
  );
}

function Staff({ can }: { can: (key: string) => boolean }) {
  const index = [
    ...(can("infractions") ? ["Infractions"] : []),
    ...(can("staff_management") ? ["Retire", "Reinstate"] : [])
  ];

  return (
    <Panel title="Staff Management" index={index}>
      <div className="two-col">
        {can("infractions") && (
          <ActionForm action="infract">
            <h2>Infract User</h2>
            <input name="target_id" placeholder="User ID or username" required />
            <input name="punishment" placeholder="Punishment" required />
            <textarea name="reason" placeholder="Reason" required />
            <button className="button primary">Create Infraction</button>
          </ActionForm>
        )}
        {can("staff_management") && (
          <>
            <ActionForm action="retire">
              <h2>Retire Staff Member</h2>
              <input name="target_id" placeholder="User ID or username" required />
              <button className="button primary">Retire</button>
            </ActionForm>
            <ActionForm action="reinstate">
              <h2>Reinstate Staff Member</h2>
              <input name="target_id" placeholder="User ID or username" required />
              <button className="button primary">Reinstate</button>
            </ActionForm>
          </>
        )}
      </div>
    </Panel>
  );
}

function Erlc({ data }: { data: DashboardData }) {
  return <Panel title="ERLC Controls" index={["Server Snapshot", "Command", "Players"]}><div className="two-col"><article className="setting-card"><h2>Server Snapshot</h2><p>Name: {fieldValue(data.erlc_server.Name)}</p><p>Players: {fieldValue(data.erlc_server.CurrentPlayers)}/{fieldValue(data.erlc_server.MaxPlayers)}</p><p>Join Key: {fieldValue(data.erlc_server.JoinKey)}</p></article><ActionForm action="erlc_command"><h2>Run Command</h2><input name="command" placeholder=":h Server restarting soon" required /><button className="button primary">Execute</button></ActionForm></div><article className="setting-card"><h2>Players</h2><div className="list-grid">{data.erlc_players.length ? data.erlc_players.map((player, index) => <div className="list-item" key={index}>{player.Player || "Unknown"}<span>{player.Team || "Unknown"}</span></div>) : <div className="list-item">No player data available.</div>}</div></article></Panel>;
}

function Partnerships({ channels }: { channels: Channel[] }) {
  return <Panel title="Partnerships" index={["Announcement"]}><ActionForm action="partnership"><h2>Send Partnership</h2><ChannelSelect name="channel_id" channels={channels} /><textarea name="body" placeholder="Partnership message body" required /><button className="button primary">Send Partnership</button></ActionForm></Panel>;
}

function Embeds({ channels }: { channels: Channel[] }) {
  const [draft, setDraft] = useState<EmbedDraft>(DEFAULT_EMBED_DRAFT);
  const [fields, setFields] = useState<EmbedFieldDraft[]>([
    { id: 1, name: "Rules", value: "Be respectful and follow staff directions.", inline: false }
  ]);
  const visibleFields = fields.filter((field) => field.name.trim() || field.value.trim());
  const updateDraft = (key: keyof EmbedDraft, value: string | boolean) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const updateField = (id: number, patch: Partial<EmbedFieldDraft>) => {
    setFields((current) => current.map((field) => (field.id === id ? { ...field, ...patch } : field)));
  };
  const addField = () => {
    setFields((current) =>
      current.length >= 25 ? current : [...current, { id: Date.now(), name: "", value: "", inline: false }]
    );
  };
  const removeField = (id: number) => {
    setFields((current) => current.filter((field) => field.id !== id));
  };

  return (
    <Panel title="Embed Wizard" index={["Preview", "Message", "Author", "Fields", "Media"]}>
      <DashboardPostForm action="embed_send" className="embed-builder">
        <section className="embed-editor">
          <div className="embed-editor-section">
            <h2>Destination</h2>
            <ChannelSelect name="channel_id" channels={channels} />
          </div>

          <div className="embed-editor-section">
            <h2>Message</h2>
            <textarea name="content" value={draft.content} onChange={(event) => updateDraft("content", event.target.value)} placeholder="Message above the embed" />
            <input name="title" value={draft.title} onChange={(event) => updateDraft("title", event.target.value)} placeholder="Embed title" />
            <textarea name="description" value={draft.description} onChange={(event) => updateDraft("description", event.target.value)} placeholder="Embed description" />
            <input name="url" value={draft.url} onChange={(event) => updateDraft("url", event.target.value)} placeholder="Title URL" />
            <label className="color-input-row">
              <span>Accent color</span>
              <input type="color" value={safeEmbedColor(draft.color)} onChange={(event) => updateDraft("color", event.target.value)} aria-label="Embed accent color" />
              <input name="color" value={draft.color} onChange={(event) => updateDraft("color", event.target.value)} placeholder="#5865f2" />
            </label>
          </div>

          <div className="embed-editor-section">
            <h2>Author</h2>
            <input name="author_name" value={draft.authorName} onChange={(event) => updateDraft("authorName", event.target.value)} placeholder="Author name" />
            <input name="author_url" value={draft.authorUrl} onChange={(event) => updateDraft("authorUrl", event.target.value)} placeholder="Author URL" />
            <input name="author_icon_url" value={draft.authorIconUrl} onChange={(event) => updateDraft("authorIconUrl", event.target.value)} placeholder="Author icon URL" />
          </div>

          <div className="embed-editor-section">
            <div className="panel-title-row">
              <h2>Fields</h2>
              <button type="button" className="button ghost" onClick={addField} disabled={fields.length >= 25}>
                <Plus size={16} />
                Add Field
              </button>
            </div>
            <input type="hidden" name="fields" value={embedFieldsPayload(fields)} />
            <div className="embed-field-list">
              {fields.map((field) => (
                <div className="embed-field-editor" key={field.id}>
                  <input value={field.name} onChange={(event) => updateField(field.id, { name: event.target.value })} placeholder="Field name" />
                  <textarea value={field.value} onChange={(event) => updateField(field.id, { value: event.target.value })} placeholder="Field value" />
                  <label className="switch-line">
                    <input type="checkbox" checked={field.inline} onChange={(event) => updateField(field.id, { inline: event.target.checked })} />
                    <span>Inline</span>
                  </label>
                  <button type="button" className="icon-button danger" aria-label="Remove field" onClick={() => removeField(field.id)}>
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="embed-editor-section">
            <h2>Media</h2>
            <input name="thumbnail_url" value={draft.thumbnailUrl} onChange={(event) => updateDraft("thumbnailUrl", event.target.value)} placeholder="Thumbnail URL" />
            <input name="image_url" value={draft.imageUrl} onChange={(event) => updateDraft("imageUrl", event.target.value)} placeholder="Image URL" />
            <input name="footer_text" value={draft.footerText} onChange={(event) => updateDraft("footerText", event.target.value)} placeholder="Footer text" />
            <input name="footer_icon_url" value={draft.footerIconUrl} onChange={(event) => updateDraft("footerIconUrl", event.target.value)} placeholder="Footer icon URL" />
            <label className="switch-line">
              <input type="checkbox" name="timestamp" checked={draft.timestamp} onChange={(event) => updateDraft("timestamp", event.target.checked)} />
              <span>Timestamp</span>
            </label>
          </div>

          <button className="button primary embed-send-button">
            <Send size={16} />
            Send Embed
          </button>
        </section>

        <aside className="embed-preview-panel" aria-label="Embed preview">
          <div className="discord-preview">
            <div className="discord-avatar">CU</div>
            <div className="discord-message">
              <div className="discord-message-header">
                <strong>CSRP Utilities</strong>
                <span>Today at {new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
              </div>
              {draft.content && <div className="discord-content">{previewLines(draft.content)}</div>}
              <div className="discord-embed" style={{ borderLeftColor: safeEmbedColor(draft.color) }}>
                <div className="discord-embed-main">
                  {draft.authorName && (
                    <div className="discord-embed-author">
                      {draft.authorIconUrl && <img src={draft.authorIconUrl} alt="" />}
                      <span>{draft.authorName}</span>
                    </div>
                  )}
                  {draft.title && <strong className="discord-embed-title">{draft.title}</strong>}
                  {draft.description && <p>{previewLines(draft.description)}</p>}
                  {visibleFields.length > 0 && (
                    <div className="discord-embed-fields">
                      {visibleFields.map((field) => (
                        <div className={field.inline ? "inline" : ""} key={field.id}>
                          {field.name && <strong>{field.name}</strong>}
                          {field.value && <span>{previewLines(field.value)}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                  {draft.imageUrl && <img className="discord-embed-image" src={draft.imageUrl} alt="" />}
                  {(draft.footerText || draft.footerIconUrl || draft.timestamp) && (
                    <div className="discord-embed-footer">
                      {draft.footerIconUrl && <img src={draft.footerIconUrl} alt="" />}
                      <span>{[draft.footerText, draft.timestamp ? "Today" : ""].filter(Boolean).join(" • ")}</span>
                    </div>
                  )}
                </div>
                {draft.thumbnailUrl && <img className="discord-embed-thumbnail" src={draft.thumbnailUrl} alt="" />}
              </div>
            </div>
          </div>
        </aside>
      </DashboardPostForm>
    </Panel>
  );
}

function Modlogs({ data }: { data: DashboardData }) {
  return <Panel title="Modlogs" index={["Lookup", "Clear", "Results"]}><div className="two-col"><form className="setting-card form-grid" method="get" action="/dashboard"><h2>Lookup User Logs</h2><input name="modlog_user_id" placeholder="User ID or username" defaultValue={data.modlog_user_id} /><button className="button primary">View Logs</button></form><ActionForm action="modlogs_clear_user"><h2>Clear User Logs</h2><input name="target_id" placeholder="User ID or username" required /><button className="button primary">Clear User Logs</button></ActionForm></div><ActionForm action="modlogs_clear_all" danger><h2>Clear All Modlogs</h2><button className="button danger">Clear Everything</button></ActionForm>{data.modlog_results && <article className="setting-card"><h2>Results for {data.modlog_user_id}</h2><div className="list-grid">{data.modlog_results.length ? data.modlog_results.map((log, index) => <div className="list-item" key={index}>{log.action}<span>Case #{log.case_id} | {log.reason}</span></div>) : <div className="list-item">No modlogs found.</div>}</div></article>}</Panel>;
}

function Blacklist() {
  return <Panel title="Command Blacklist" index={["Add", "Remove"]}><div className="two-col"><ActionForm action="blacklist_add"><h2>Add User</h2><input name="target_id" placeholder="User ID or username" required /><button className="button primary">Blacklist</button></ActionForm><ActionForm action="blacklist_remove"><h2>Remove User</h2><input name="target_id" placeholder="User ID or username" required /><button className="button primary">Remove</button></ActionForm></div></Panel>;
}

function Docker() {
  return <Panel title="Docker Commands" index={["Database"]}><ActionForm action="docker_exec"><h2>Run Database Command</h2><input name="database" placeholder="Database name" required /><textarea name="command" placeholder="SQL command" required /><button className="button primary">Execute</button></ActionForm></Panel>;
}

function BotUpdates({ channels }: { channels: Channel[] }) {
  return <Panel title="Bot Updates" index={["Presence", "Message"]}><div className="two-col"><ActionForm action="bot_status"><h2>Update Presence</h2><input name="status_text" placeholder="New status text" required /><button className="button primary">Update Status</button></ActionForm><ActionForm action="bot_message"><h2>Send Bot Message</h2><ChannelSelect name="channel_id" channels={channels} /><textarea name="content" placeholder="Message content" required /><button className="button primary">Send Message</button></ActionForm></div></Panel>;
}

function BotSettings({ data }: { data: DashboardData }) {
  return <Panel title="Basic Settings" index={["Staff Roles", "Channels", "Feedback", "Rank Roles"]}><DashboardPostForm action="settings_save" className="card-stack"><article className="setting-card"><h2>Staff Roles</h2><p>{roleNames(data.settings.staff_roles, data.roles).join(", ") || "No staff roles selected"}</p><RoleSelect name="staff_roles" roles={data.roles} selected={data.settings.staff_roles} /></article><article className="setting-card"><h2>Feature Roles</h2><label>Partnerships</label><RoleSelect name="partnership_allowed_roles" roles={data.roles} selected={data.settings.partnership_allowed_roles} /><label>Embed Creation</label><RoleSelect name="embed_allowed_roles" roles={data.roles} selected={data.settings.embed_allowed_roles} /><label>Retire / Reinstate</label><RoleSelect name="retire_allowed_roles" roles={data.roles} selected={data.settings.retire_allowed_roles} /></article><article className="setting-card"><h2>Channels</h2><label>Retirement Log Channel</label><ChannelSelect name="retirement_log_channel" channels={data.channels} selected={data.settings.retirement_log_channel} /><label>Staff Feedback Channel</label><ChannelSelect name="staff_feedback_channel" channels={data.channels} selected={data.settings.staff_feedback_channel} /></article><article className="setting-card"><h2>Feedback</h2><label className="switch-line"><input type="checkbox" name="feedback_enabled" defaultChecked={Boolean(data.settings.feedback_enabled)} /><span>Feedback enabled</span></label><textarea name="feedback_questions" defaultValue={(data.settings.feedback_questions || []).join("\n")} /></article><article className="setting-card"><h2>Rank Role Mapping</h2>{data.rank_order.map((rank) => <label key={rank}>{rank}<RoleSelect name={`rank::${rank}`} roles={data.roles} selected={data.settings.rank_roles?.[rank]} multiple={false} /></label>)}</article><button className="button primary">Save Bot Settings</button></DashboardPostForm></Panel>;
}

function AccessManager({ data }: { data: DashboardData }) {
  return <Panel title="Access Manager" index={["Full Access", "Features"]}><DashboardPostForm action="access_save" className="card-stack"><article className="setting-card"><h2>Full Dashboard Access</h2><RoleSelect name="full_access_roles" roles={data.roles} selected={data.permissions_data.full_access_roles} /></article>{data.features.map((feature) => <article className="setting-card" key={feature.key}><h2>{feature.label}</h2><RoleSelect name={`feature::${feature.key}`} roles={data.roles} selected={data.permissions_data.features[feature.key]} /></article>)}<button className="button primary">Save Access Rules</button></DashboardPostForm></Panel>;
}

function Panel({ title, index, children }: { title: string; index: string[]; children: React.ReactNode }) {
  return <section className="settings-layout"><nav className="section-index"><strong>{title}</strong>{index.map((item) => <span key={item}>{item}</span>)}</nav><div className="card-stack">{children}</div></section>;
}
