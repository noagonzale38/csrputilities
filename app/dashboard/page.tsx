"use client";

import {
  Ban,
  Bot,
  ChevronDown,
  Database,
  FileText,
  Gauge,
  LogOut,
  Megaphone,
  RefreshCw,
  Send,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  UserMinus,
  Users
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type Role = { id: string; name: string; position: number; color: string };
type Channel = { id: string; name: string; position: number };
type Feature = { key: string; label: string };
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

const navigation = [
  ["overview", "Overview", Gauge],
  ["moderation", "Moderation", ShieldAlert],
  ["staff", "Staff", UserMinus],
  ["erlc", "ERLC", Bot],
  ["partnerships", "Partnerships", Megaphone],
  ["embeds", "Embeds", FileText],
  ["modlogs", "Modlogs", FileText],
  ["blacklist", "Blacklist", Ban],
  ["docker", "Docker", Database],
  ["updates", "Bot Updates", Send],
  ["settings", "Settings", Settings],
  ["access", "Access", Users]
] as const;

const accessMap: Record<string, string[]> = {
  moderation: ["moderation", "infractions"],
  staff: ["staff_management"],
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

function useDashboardData() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
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
      .then((payload) => payload && setData(payload))
      .catch((err) => setError(err.message));
  }, []);

  return { data, error };
}

function fieldValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not set";
  return String(value);
}

function roleNames(ids: unknown, roles: Role[]) {
  const selected = Array.isArray(ids) ? ids.map(String) : [];
  return roles.filter((role) => selected.includes(role.id)).map((role) => role.name);
}

function RoleSelect({ name, roles, selected, multiple = true }: { name: string; roles: Role[]; selected?: unknown; multiple?: boolean }) {
  const values = Array.isArray(selected) ? selected.map(String) : selected ? [String(selected)] : [];
  return (
    <select name={name} multiple={multiple} size={multiple ? 6 : 1} defaultValue={values}>
      {!multiple && <option value="">No role selected</option>}
      {roles.map((role) => (
        <option key={role.id} value={role.id}>
          {role.name}
        </option>
      ))}
    </select>
  );
}

function ChannelSelect({ name, channels, selected }: { name: string; channels: Channel[]; selected?: unknown }) {
  return (
    <select name={name} defaultValue={selected ? String(selected) : ""}>
      <option value="">No channel selected</option>
      {channels.map((channel) => (
        <option key={channel.id} value={channel.id}>
          #{channel.name}
        </option>
      ))}
    </select>
  );
}

function ActionForm({ action, children, danger = false }: { action: string; children: React.ReactNode; danger?: boolean }) {
  return (
    <form className={`setting-card form-grid ${danger ? "danger-card" : ""}`} method="post" action={`/api/actions/${action}`}>
      {children}
    </form>
  );
}

export default function Dashboard() {
  const { data, error } = useDashboardData();
  const [active, setActive] = useState("overview");

  const visibleNav = useMemo(() => {
    if (!data) return navigation.slice(0, 1);
    return navigation.filter(([id]) => id === "overview" || accessMap[id]?.some((key) => data.feature_access[key]));
  }, [data]);

  if (error) {
    return <main className="state-page"><p>{error}</p></main>;
  }

  if (!data) {
    return <main className="state-page"><RefreshCw className="spin" /><p>Loading dashboard...</p></main>;
  }

  const can = (key: string) => Boolean(data.feature_access[key]);

  return (
    <main className="app-shell">
      <aside className="rail">
        <div className="guild-badge">{data.guild.icon_url ? <img src={data.guild.icon_url} alt="" /> : data.guild.name.slice(0, 2)}</div>
        <nav>
          {visibleNav.map(([id, label, Icon]) => (
            <button key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)} title={label}>
              <Icon size={18} />
            </button>
          ))}
        </nav>
        <a href="/api/logout" title="Logout"><LogOut size={18} /></a>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="crumbs">
            <span>Home</span><span>/</span><span>{data.guild.name}</span><span>/</span><strong>Dashboard</strong>
          </div>
          <div className="top-actions">
            <button className="button ghost" onClick={() => window.location.reload()}><RefreshCw size={16} />Refresh</button>
            <a className="button ghost" href="#settings"><SlidersHorizontal size={16} />Settings</a>
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
          {active === "staff" && <Staff />}
          {active === "erlc" && <Erlc data={data} />}
          {active === "partnerships" && <Partnerships channels={data.channels} />}
          {active === "embeds" && <Embeds channels={data.channels} />}
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

function Overview({ data }: { data: DashboardData }) {
  const stats = [
    ["Members", data.stats.member_count],
    ["Roles", data.stats.role_count],
    ["Channels", data.stats.channel_count],
    ["Modlogs", data.stats.modlog_count],
    ["Retirements", data.stats.retirement_count],
    ["ERLC Players", data.stats.erlc_player_count],
    ["Command Blacklists", data.stats.command_blacklist_count],
    ["Latency", `${data.stats.bot_latency_ms}ms`]
  ];

  return (
    <>
      <div className="page-title">
        <p>CSRP Utilities</p>
        <h1>Dashboard</h1>
        <span>{data.member.display_name} in {data.guild.name}</span>
      </div>
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
    <Panel title="Moderation" index={["Warn", "Kick / Ban", "Timeouts", "Infractions"]}>
      {can("moderation") && (
        <div className="two-col">
          {["warn", "kick", "ban", "unban"].map((action) => (
            <ActionForm action={action} key={action}>
              <h2>{action[0].toUpperCase() + action.slice(1)} User</h2>
              <input name="target_id" placeholder="User ID" required />
              <textarea name="reason" placeholder="Reason" required />
              <button className="button primary">Submit</button>
            </ActionForm>
          ))}
          <ActionForm action="mute"><h2>Apply Timeout</h2><input name="target_id" placeholder="User ID" required /><input name="duration" placeholder="10m / 2h / 1d" required /><textarea name="reason" placeholder="Reason" required /><button className="button primary">Apply Timeout</button></ActionForm>
          <ActionForm action="unmute"><h2>Remove Timeout</h2><input name="target_id" placeholder="User ID" required /><textarea name="reason" placeholder="Reason" required /><button className="button primary">Remove Timeout</button></ActionForm>
        </div>
      )}
      {can("infractions") && <ActionForm action="infract"><h2>Infract User</h2><input name="target_id" placeholder="User ID" required /><input name="punishment" placeholder="Punishment" required /><textarea name="reason" placeholder="Reason" required /><button className="button primary">Create Infraction</button></ActionForm>}
    </Panel>
  );
}

function Staff() {
  return <Panel title="Staff Management" index={["Retire", "Reinstate"]}><div className="two-col"><ActionForm action="retire"><h2>Retire Staff Member</h2><input name="target_id" placeholder="User ID" required /><button className="button primary">Retire</button></ActionForm><ActionForm action="reinstate"><h2>Reinstate Staff Member</h2><input name="target_id" placeholder="User ID" required /><button className="button primary">Reinstate</button></ActionForm></div></Panel>;
}

function Erlc({ data }: { data: DashboardData }) {
  return <Panel title="ERLC Controls" index={["Server Snapshot", "Command", "Players"]}><div className="two-col"><article className="setting-card"><h2>Server Snapshot</h2><p>Name: {fieldValue(data.erlc_server.Name)}</p><p>Players: {fieldValue(data.erlc_server.CurrentPlayers)}/{fieldValue(data.erlc_server.MaxPlayers)}</p><p>Join Key: {fieldValue(data.erlc_server.JoinKey)}</p></article><ActionForm action="erlc_command"><h2>Run Command</h2><input name="command" placeholder=":h Server restarting soon" required /><button className="button primary">Execute</button></ActionForm></div><article className="setting-card"><h2>Players</h2><div className="list-grid">{data.erlc_players.length ? data.erlc_players.map((player, index) => <div className="list-item" key={index}>{player.Player || "Unknown"}<span>{player.Team || "Unknown"}</span></div>) : <div className="list-item">No player data available.</div>}</div></article></Panel>;
}

function Partnerships({ channels }: { channels: Channel[] }) {
  return <Panel title="Partnerships" index={["Announcement"]}><ActionForm action="partnership"><h2>Send Partnership</h2><ChannelSelect name="channel_id" channels={channels} /><textarea name="body" placeholder="Partnership message body" required /><button className="button primary">Send Partnership</button></ActionForm></Panel>;
}

function Embeds({ channels }: { channels: Channel[] }) {
  return <Panel title="Embed Wizard" index={["Channel", "Content", "Style", "Media"]}><ActionForm action="embed_send"><h2>Build Embed</h2><ChannelSelect name="channel_id" channels={channels} /><textarea name="content" placeholder="Optional text above the embed" /><input name="title" placeholder="Embed title" /><textarea name="description" placeholder="Embed description" /><textarea name="fields" placeholder={"Name | Value | inline\nRules | Be respectful | true"} /><input name="color" defaultValue="#5865f2" /><input name="url" placeholder="https://example.com" /><input name="thumbnail_url" placeholder="Thumbnail URL" /><input name="image_url" placeholder="Image URL" /><button className="button primary">Send Embed</button></ActionForm></Panel>;
}

function Modlogs({ data }: { data: DashboardData }) {
  return <Panel title="Modlogs" index={["Lookup", "Clear", "Results"]}><div className="two-col"><form className="setting-card form-grid" method="get" action="/dashboard"><h2>Lookup User Logs</h2><input name="modlog_user_id" placeholder="User ID" defaultValue={data.modlog_user_id} /><button className="button primary">View Logs</button></form><ActionForm action="modlogs_clear_user"><h2>Clear User Logs</h2><input name="target_id" placeholder="User ID" required /><button className="button primary">Clear User Logs</button></ActionForm></div><ActionForm action="modlogs_clear_all" danger><h2>Clear All Modlogs</h2><button className="button danger">Clear Everything</button></ActionForm>{data.modlog_results && <article className="setting-card"><h2>Results for {data.modlog_user_id}</h2><div className="list-grid">{data.modlog_results.length ? data.modlog_results.map((log, index) => <div className="list-item" key={index}>{log.action}<span>Case #{log.case_id} | {log.reason}</span></div>) : <div className="list-item">No modlogs found.</div>}</div></article>}</Panel>;
}

function Blacklist() {
  return <Panel title="Command Blacklist" index={["Add", "Remove"]}><div className="two-col"><ActionForm action="blacklist_add"><h2>Add User</h2><input name="target_id" placeholder="User ID" required /><button className="button primary">Blacklist</button></ActionForm><ActionForm action="blacklist_remove"><h2>Remove User</h2><input name="target_id" placeholder="User ID" required /><button className="button primary">Remove</button></ActionForm></div></Panel>;
}

function Docker() {
  return <Panel title="Docker Commands" index={["Database"]}><ActionForm action="docker_exec"><h2>Run Database Command</h2><input name="database" placeholder="Database name" required /><textarea name="command" placeholder="SQL command" required /><button className="button primary">Execute</button></ActionForm></Panel>;
}

function BotUpdates({ channels }: { channels: Channel[] }) {
  return <Panel title="Bot Updates" index={["Presence", "Message"]}><div className="two-col"><ActionForm action="bot_status"><h2>Update Presence</h2><input name="status_text" placeholder="New status text" required /><button className="button primary">Update Status</button></ActionForm><ActionForm action="bot_message"><h2>Send Bot Message</h2><ChannelSelect name="channel_id" channels={channels} /><textarea name="content" placeholder="Message content" required /><button className="button primary">Send Message</button></ActionForm></div></Panel>;
}

function BotSettings({ data }: { data: DashboardData }) {
  return <Panel title="Basic Settings" index={["Staff Roles", "Channels", "Feedback", "Rank Roles"]}><form className="card-stack" method="post" action="/api/actions/settings_save"><article className="setting-card"><h2>Staff Roles</h2><p>{roleNames(data.settings.staff_roles, data.roles).join(", ") || "No staff roles selected"}</p><RoleSelect name="staff_roles" roles={data.roles} selected={data.settings.staff_roles} /></article><article className="setting-card"><h2>Feature Roles</h2><label>Partnerships</label><RoleSelect name="partnership_allowed_roles" roles={data.roles} selected={data.settings.partnership_allowed_roles} /><label>Embed Creation</label><RoleSelect name="embed_allowed_roles" roles={data.roles} selected={data.settings.embed_allowed_roles} /><label>Retire / Reinstate</label><RoleSelect name="retire_allowed_roles" roles={data.roles} selected={data.settings.retire_allowed_roles} /></article><article className="setting-card"><h2>Channels</h2><label>Retirement Log Channel</label><ChannelSelect name="retirement_log_channel" channels={data.channels} selected={data.settings.retirement_log_channel} /><label>Staff Feedback Channel</label><ChannelSelect name="staff_feedback_channel" channels={data.channels} selected={data.settings.staff_feedback_channel} /></article><article className="setting-card"><h2>Feedback</h2><label className="switch-line"><input type="checkbox" name="feedback_enabled" defaultChecked={Boolean(data.settings.feedback_enabled)} /><span>Feedback enabled</span></label><textarea name="feedback_questions" defaultValue={(data.settings.feedback_questions || []).join("\n")} /></article><article className="setting-card"><h2>Rank Role Mapping</h2>{data.rank_order.map((rank) => <label key={rank}>{rank}<RoleSelect name={`rank::${rank}`} roles={data.roles} selected={data.settings.rank_roles?.[rank]} multiple={false} /></label>)}</article><button className="button primary">Save Bot Settings</button></form></Panel>;
}

function AccessManager({ data }: { data: DashboardData }) {
  return <Panel title="Access Manager" index={["Full Access", "Features"]}><form className="card-stack" method="post" action="/api/actions/access_save"><article className="setting-card"><h2>Full Dashboard Access</h2><RoleSelect name="full_access_roles" roles={data.roles} selected={data.permissions_data.full_access_roles} /></article>{data.features.map((feature) => <article className="setting-card" key={feature.key}><h2>{feature.label}</h2><RoleSelect name={`feature::${feature.key}`} roles={data.roles} selected={data.permissions_data.features[feature.key]} /></article>)}<button className="button primary">Save Access Rules</button></form></Panel>;
}

function Panel({ title, index, children }: { title: string; index: string[]; children: React.ReactNode }) {
  return <section className="settings-layout"><nav className="section-index"><strong>{title}</strong>{index.map((item) => <span key={item}>{item}</span>)}</nav><div className="card-stack">{children}</div></section>;
}
