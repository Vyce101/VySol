const HIDE_DELAY_MS = 850;
const FADE_DURATION_MS = 250;
const SCROLLBAR_CLASS = "show-vertical-scrollbar";
const FADING_CLASS = "fade-vertical-scrollbar";

type ScrollState = {
  top: number;
  hideTimer: number | null;
  fadeTimer: number | null;
};

export function installVerticalScrollbarVisibility() {
  const scrollStates = new WeakMap<HTMLElement, ScrollState>();
  const activeScrollAreas = new Set<HTMLElement>();

  function stateFor(element: HTMLElement) {
    let state = scrollStates.get(element);
    if (!state) {
      state = { top: element.scrollTop, hideTimer: null, fadeTimer: null };
      scrollStates.set(element, state);
    }
    return state;
  }

  function markScrolling(element: HTMLElement) {
    const state = stateFor(element);
    element.classList.remove(FADING_CLASS);
    element.classList.add(SCROLLBAR_CLASS);
    activeScrollAreas.add(element);
    if (state.hideTimer !== null) window.clearTimeout(state.hideTimer);
    if (state.fadeTimer !== null) window.clearTimeout(state.fadeTimer);
    state.fadeTimer = null;
    state.hideTimer = window.setTimeout(() => {
      element.classList.remove(SCROLLBAR_CLASS);
      state.hideTimer = null;
      if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        activeScrollAreas.delete(element);
        return;
      }
      element.classList.add(FADING_CLASS);
      state.fadeTimer = window.setTimeout(() => {
        element.classList.remove(FADING_CLASS);
        activeScrollAreas.delete(element);
        state.fadeTimer = null;
      }, FADE_DURATION_MS);
    }, HIDE_DELAY_MS);
  }

  function onScroll(event: Event) {
    const target = event.target;
    const element = target === document
      ? document.scrollingElement
      : target instanceof HTMLElement
        ? target
        : null;
    if (!(element instanceof HTMLElement)) return;

    const state = scrollStates.get(element);
    if (!state) {
      scrollStates.set(element, { top: element.scrollTop, hideTimer: null, fadeTimer: null });
      if (element.scrollTop !== 0) markScrolling(element);
      return;
    }
    if (element.scrollTop === state.top) return;

    state.top = element.scrollTop;
    markScrolling(element);
  }

  document.addEventListener("scroll", onScroll, true);

  return () => {
    document.removeEventListener("scroll", onScroll, true);
    for (const element of activeScrollAreas) {
      element.classList.remove(SCROLLBAR_CLASS);
      element.classList.remove(FADING_CLASS);
      const state = scrollStates.get(element);
      if (state?.hideTimer !== null && state?.hideTimer !== undefined) {
        window.clearTimeout(state.hideTimer);
      }
      if (state?.fadeTimer !== null && state?.fadeTimer !== undefined) {
        window.clearTimeout(state.fadeTimer);
      }
    }
  };
}
