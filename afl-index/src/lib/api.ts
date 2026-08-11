/**
 * API client for the AFL Predictor FastAPI backend (port 8001).
 * Falls back to static demo data when the API is unreachable.
 */

export const API_BASE = "http://localhost:8001";

export interface APIEvent {
  id: string;
  home: string;
  away: string;
  venue: string;
  commence_time: string;
  slot: string;
  p_home: number;
  p_away: number;
  pick: string;
  rain_mm: number | null;
  wind_kmh: number | null;
  h2h: string;
  top_disposals: [string, string, number][];
  top_goals: [string, string, number][];
}

export interface APIProp {
  player: string;
  team: string;
  stat: string;
  milestone: string;
  model_p: number;
  sb_odds: number | null;
  proj: number;
  edge: number | null;
  ev: number | null;
  kelly: number | null;
  implied_p: number | null;
}

export interface APISGMLeg {
  player: string;
  player_scraped: string;
  team: string;
  stat: string;
  milestone: string;
  line: number;
  odds: number;
  prob: number;
}

export interface APITargetMulti {
  target: number;
  result: {
    legs: APISGMLeg[];
    combined_odds: number;
    joint_prob: number;
    implied_prob: number;
    edge: number;
    n_legs: number;
    reasons: string[];
  } | null;
}

export interface APIValueBet {
  game: string;
  event_id: string;
  player: string;
  team: string;
  stat: string;
  milestone: string;
  model_p: number;
  sb_odds: number;
  implied_p: number;
  edge: number;
  ev: number;
  kelly: number;
  proj: number | null;
  hit_last_5: number | null;   // 0.0–1.0 fraction of last 5 games where line hit
  hit_vs_opp: number | null;   // fraction of last N games vs this opponent
  opp_n: number;               // how many opponent meetings we have data for
  tier: "lock" | "strong" | "value";
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API POST ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export type MultiType =
  | "risk_low" | "risk_med" | "risk_high"
  | "target_2" | "target_3" | "target_5" | "target_10"
  | "target_2_safe" | "target_3_safe" | "target_5_safe" | "target_10_safe";

export interface TrackerLeg {
  player: string;
  team: string;
  stat: string;
  milestone: string;
  line: number;
  odds: number;
  prob: number;
  opponent?: string;
  result: boolean | null;
  actual_value: number | null;
}

export interface TrackerBet {
  id: string;
  placed_at: string;
  game: string;
  event_id: string;
  game_date: string;
  multi_type: MultiType;
  multi_label: string;
  legs: TrackerLeg[];
  combined_odds: number;
  stake: number;
  potential_return: number;
  status: "pending" | "won" | "lost";
  result_checked_at: string | null;
  pnl: number | null;
}

export interface CurrentMulti {
  multi_type: MultiType;
  multi_label: string;
  legs: TrackerLeg[];
  combined_odds: number;
  joint_prob: number;
}

export interface CurrentGame {
  event_id: string;
  game: string;
  home: string;
  away: string;
  game_date: string;
  multis: CurrentMulti[];
}

export interface APIBestLine {
  player: string;
  team: string;
  stat: string;
  milestone: string;
  model_p: number;
  sb_odds: number | null;
  implied_p: number | null;
  edge: number | null;
  ev: number | null;
  kelly: number | null;
  proj: number | null;
  hit_last_5: number | null;
  hit_last_10: number | null;
  hit_vs_opp: number | null;
  opp_n: number;
  tier: "lock" | "strong" | "value";
}

export interface LiveGame {
  id: number;
  date: string;       // "2026-06-27"
  time_utc: string;
  venue: string;
  week: number | null;
  status: string;     // NS / Q1 / Q2 / HT / Q3 / Q4 / OT / FT
  status_long: string;
  home: string;
  away: string;
  home_score: number;
  away_score: number;
  home_goals: number;
  home_behinds: number;
  away_goals: number;
  away_behinds: number;
}

export interface LiveStatus {
  daily_used: number;
  daily_limit: number;
  daily_remaining: number;
  last_updated: string | null;
  last_fetch_ok: string | null;
  active_window: boolean;
  fetch_interval_sec: number | null;
  reset_date: string;
}

export interface LiveGamesResponse {
  games: LiveGame[];
  last_updated: string | null;
  last_fetch_ok: string | null;
  daily_used: number;
  daily_limit: number;
  daily_remaining: number;
}

export interface HistoricalRound {
  season: number;
  round: string;
  date: string;
}

export interface HistoricalGame {
  home: string;
  away: string;
  venue: string;
  date: string;
  home_score: number;
  away_score: number;
  home_goals: number;
  home_behinds: number;
  away_goals: number;
  away_behinds: number;
  winner: string | null;
  top_disposals: [string, string, number][];
}

export interface TeamStyle {
  team: string; games: number; style: string;
  contested_ratio: number; kick_ratio: number;
  avg_clearances: number; avg_tackles: number; avg_inside50: number;
  avg_rebounds: number; avg_goals: number; avg_clangers: number;
  avg_cont_marks: number; avg_i50_marks: number;
}
export interface StyleMatchupCell { win_rate: number | null; n: number; }
export interface StyleMatchupRow { style: string; results: StyleMatchupCell[]; }
export interface StyleMatchups {
  styles: string[]; matrix: StyleMatchupRow[];
  style_teams: Record<string, string[]>; team_styles: Record<string, string>;
}
export interface PositionConcessionRow {
  position: string; avg_disposals: number; avg_goals: number;
  avg_clearances: number; avg_rebounds: number;
  disp_vs_avg: number; goal_vs_avg: number; n_games: number;
}
export interface TeamConcession { team: string; positions: PositionConcessionRow[]; }
export interface NotableFinding {
  team: string; position: string; disp_vs_avg: number;
  avg_disposals: number; direction: string;
}
export interface PositionConcession {
  available: boolean; reason?: string;
  teams?: TeamConcession[];
  league_avg?: { position: string; avg_disposals: number; avg_goals: number }[];
  notable?: NotableFinding[];
  positions?: string[];
}

export interface LiveProgress {
  [betId: string]: {
    game: string;
    status: string;
    updated: string;
    legs: { player: string; stat: string; milestone: string; line: number;
            current: number | null; hit: boolean }[];
    legs_hit: number;
    legs_total: number;
  };
}

export interface RoleLeakTeam {
  team: string;
  roles: { role: string; avg_disposals: number; vs_league: number; n_player_games: number }[];
}

export interface RoleLeaks {
  available: boolean;
  teams: RoleLeakTeam[];
  league_avg: Record<string, number>;
  notable: { team: string; role: string; vs_league: number; avg_disposals: number; direction: string }[];
  exploits: { player: string; vs_team: string; role: string; disposals: number; season_avg: number; over: number; date: string }[];
  roles: string[];
}

export const api = {
  events: () => get<APIEvent[]>("/api/events"),
  gameProps: (id: string) => get<APIProp[]>(`/api/game/${id}/props`),
  gameBestLines: (id: string) => get<APIBestLine[]>(`/api/game/${id}/best-lines`),
  gameSGM: (id: string) => get<APISGMLeg[]>(`/api/game/${id}/sgm`),
  gameTargetMultis: (id: string, floor = 0.6) =>
    get<APITargetMulti[]>(`/api/game/${id}/multis?floor=${floor}`),
  value: (minEdge = 0.04) => get<APIValueBet[]>(`/api/value?min_edge=${minEdge}`),
  health: () => get<{ status: string }>("/api/health"),
  live: {
    games: () => get<LiveGamesResponse>("/api/live/games"),
    status: () => get<LiveStatus>("/api/live/status"),
    refresh: () => post<LiveGamesResponse>("/api/live/refresh"),
  },
  historical: {
    rounds: () => get<HistoricalRound[]>("/api/historical/rounds"),
    round: (season: number, rnd: string) =>
      get<HistoricalGame[]>(`/api/historical/round?season=${season}&rnd=${encodeURIComponent(rnd)}`),
  },
  analysis: {
    teamStyles:          () => get<TeamStyle[]>("/api/analysis/team-styles"),
    styleMatchups:       () => get<StyleMatchups>("/api/analysis/style-matchups"),
    positionConcession:  () => get<PositionConcession>("/api/analysis/position-concession"),
    roleLeaks:           () => get<RoleLeaks>("/api/analysis/role-leaks"),
    refresh:             () => post<{ ok: boolean }>("/api/analysis/refresh"),
  },
  tracker: {
    bets: () => get<{ bets: TrackerBet[] }>("/api/tracker"),
    currentMultis: () => get<CurrentGame[]>("/api/tracker/current-multis"),
    place: (bets: Omit<TrackerBet, "id" | "placed_at" | "status" | "result_checked_at" | "pnl" | "stake" | "potential_return">[]) =>
      post<{ placed: number }>("/api/tracker/place", { bets }),
    autoPlace: () => post<{ auto_placed: number; bets: TrackerBet[] }>("/api/tracker/auto-place"),
    check: () => post<{ updated: number; bets: TrackerBet[] }>("/api/tracker/check"),
    liveProgress: () => get<LiveProgress>("/api/tracker/live-progress"),
  },
};
