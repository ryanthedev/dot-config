/** The time the footer label shows, as HH:MM in local time; '' before the first tick. */
export type ClockTime = string

declare module 'claude-code' {
  interface PluginState {
    clock: { time: ClockTime }
  }
}
