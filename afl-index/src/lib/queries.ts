/**
 * React Query hooks for the AFL Predictor API.
 * All queries have a 5-min stale time so the UI stays responsive.
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { APIBestLine, TrackerBet, CurrentGame, HistoricalRound, HistoricalGame, LiveGame, LiveStatus, LiveGamesResponse, TeamStyle, StyleMatchups, PositionConcession } from "./api";
export type { APIBestLine, TrackerBet, CurrentGame, HistoricalRound, HistoricalGame, LiveGame, LiveStatus, LiveGamesResponse, TeamStyle, StyleMatchups, PositionConcession };

/** Mirror the backend fetch schedule so the UI refreshes in sync. */
function liveRefetchMs(): number {
  const now = new Date();
  const wd = now.getDay();  // 0=Sun, 1=Mon, …, 4=Thu, 5=Fri, 6=Sat
  const h  = now.getHours();
  if ((wd === 6 || wd === 0) && h >= 13 && h < 23) return 6 * 60 * 1000;   // Sat/Sun peak
  if ((wd === 4 || wd === 5) && h >= 19 && h < 23) return 2 * 60 * 1000;   // Thu/Fri peak
  return 20 * 60 * 1000;                                                     // default
}

const FIVE_MIN = 1000 * 60 * 5;

export function useEvents() {
  return useQuery({
    queryKey: ["events"],
    queryFn: api.events,
    staleTime: FIVE_MIN,
    retry: 1,
  });
}

export function useGameProps(eventId: string | null) {
  return useQuery({
    queryKey: ["props", eventId],
    queryFn: () => api.gameProps(eventId!),
    enabled: !!eventId,
    staleTime: FIVE_MIN,
    retry: 1,
  });
}

export function useGameSGM(eventId: string | null) {
  return useQuery({
    queryKey: ["sgm", eventId],
    queryFn: () => api.gameSGM(eventId!),
    enabled: !!eventId,
    staleTime: FIVE_MIN,
    retry: 1,
  });
}

export function useGameTargetMultis(eventId: string | null, floor = 0.3) {
  return useQuery({
    queryKey: ["target-multis", eventId, floor],
    queryFn: () => api.gameTargetMultis(eventId!, floor),
    enabled: !!eventId,
    staleTime: FIVE_MIN,
    retry: 1,
  });
}

export function useGameBestLines(eventId: string | null) {
  return useQuery({
    queryKey: ["best-lines", eventId],
    queryFn: () => api.gameBestLines(eventId!),
    enabled: !!eventId,
    staleTime: FIVE_MIN,
    retry: 1,
  });
}

export function useValueBets(minEdge = 0.04) {
  return useQuery({
    queryKey: ["value", minEdge],
    queryFn: () => api.value(minEdge),
    staleTime: FIVE_MIN,
    retry: 1,
  });
}

export function useLiveGames() {
  return useQuery({
    queryKey: ["live-games"],
    queryFn: api.live.games,
    refetchInterval: liveRefetchMs,   // recalculated each time it fires
    staleTime: 60 * 1000,
    retry: 1,
  });
}

export function useLiveRefresh() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.live.refresh,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-games"] }),
  });
}

export function useLiveStatus() {
  return useQuery({
    queryKey: ["live-status"],
    queryFn: api.live.status,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 60 * 1000,
    retry: 1,
  });
}

export function useHistoricalRounds() {
  return useQuery({
    queryKey: ["historical-rounds"],
    queryFn: api.historical.rounds,
    staleTime: Infinity,
  });
}

export function useHistoricalRound(season: number | null, rnd: string | null) {
  return useQuery({
    queryKey: ["historical-round", season, rnd],
    queryFn: () => api.historical.round(season!, rnd!),
    enabled: season !== null && rnd !== null,
    staleTime: Infinity,
  });
}

export function useTeamStyles() {
  return useQuery({ queryKey: ["analysis-team-styles"], queryFn: api.analysis.teamStyles, staleTime: Infinity });
}
export function useStyleMatchups() {
  return useQuery({ queryKey: ["analysis-style-matchups"], queryFn: api.analysis.styleMatchups, staleTime: Infinity });
}
// Season data recomputed server-side each request; refresh periodically so
// the ladder/stats pages follow results without a redeploy.
const SEASON_STALE = 5 * 60 * 1000;

export function useLadder(year = 2026) {
  return useQuery({ queryKey: ["ladder", year], queryFn: () => api.ladder(year),
                    staleTime: SEASON_STALE, refetchInterval: SEASON_STALE, retry: 1 });
}

export function useTeamStats(year = 2026) {
  return useQuery({ queryKey: ["team-stats", year], queryFn: () => api.teamStats(year),
                    staleTime: SEASON_STALE, refetchInterval: SEASON_STALE, retry: 1 });
}

export function usePlayerStats(minGames = 1) {
  return useQuery({ queryKey: ["player-stats", minGames], queryFn: () => api.playerStats(minGames),
                    staleTime: SEASON_STALE, refetchInterval: SEASON_STALE, retry: 1 });
}

export function useCurrentRound() {
  return useQuery({ queryKey: ["current-round"], queryFn: api.currentRound,
                    staleTime: SEASON_STALE, refetchInterval: SEASON_STALE, retry: 1 });
}

export function useRoleLeaks() {
  return useQuery({ queryKey: ["analysis-role-leaks"], queryFn: api.analysis.roleLeaks, staleTime: 5 * 60 * 1000 });
}

export function usePositionConcession() {
  return useQuery({ queryKey: ["analysis-position-concession"], queryFn: api.analysis.positionConcession, staleTime: 5 * 60 * 1000 });
}

/** During Sat/Sun afternoons and Thu/Fri evenings: 2-min poll so results appear without manual refresh. */
function trackerRefetchMs(): number | false {
  const now = new Date();
  const wd = now.getDay();   // 0=Sun, 6=Sat
  const h  = now.getHours();
  if ((wd === 6 || wd === 0) && h >= 13 && h <= 23) return 2 * 60 * 1000;
  if ((wd === 4 || wd === 5) && h >= 19 && h <= 23) return 2 * 60 * 1000;
  return false;
}

export function useTrackerBets() {
  return useQuery({
    queryKey: ["tracker-bets"],
    queryFn: () => api.tracker.bets(),
    staleTime: 60 * 1000,
    refetchInterval: trackerRefetchMs,
    retry: 1,
  });
}

export function useCurrentMultis() {
  return useQuery({
    queryKey: ["tracker-current"],
    queryFn: () => api.tracker.currentMultis(),
    staleTime: FIVE_MIN,
    retry: 1,
  });
}

export function usePlaceBets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.tracker.place,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tracker-bets"] }),
  });
}

export function useAutoPlace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.tracker.autoPlace,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tracker-bets"] }),
  });
}

export function useCheckResults() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.tracker.check,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tracker-bets"] }),
  });
}

export function useTrackerLiveProgress() {
  return useQuery({
    queryKey: ["tracker-live-progress"],
    queryFn: api.tracker.liveProgress,
    refetchInterval: 60_000,   // live leg values during games
    staleTime: 30_000,
    retry: 1,
  });
}
