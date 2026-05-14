import assert from "node:assert/strict";
import test from "node:test";
import { useState } from "react";
import { useSwipeDrawer } from "./use-swipe-drawer";
import {
  dispatchDocumentEvent,
  flushReact,
  installDom,
  renderReact,
} from "../../test/react-test-utils";

type MatchMediaMock = {
  mql: MediaQueryList;
  listeners: Set<(event: MediaQueryListEvent) => void>;
};

function installMatchMedia(matches: boolean): MatchMediaMock {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const mql = {
    matches,
    media: "(max-width: 767px)",
    onchange: null,
    addListener: (listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeListener: (listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
    dispatchEvent: () => true,
  } as unknown as MediaQueryList;

  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: () => mql,
  });

  return { mql, listeners };
}

function touchEvent(
  type: "touchstart" | "touchend",
  point: { clientX: number; clientY: number },
): Event {
  const event = new window.Event(type, { bubbles: true, cancelable: true });
  const payload = [point] as unknown as TouchList;
  Object.defineProperty(event, type === "touchstart" ? "touches" : "changedTouches", {
    configurable: true,
    value: payload,
  });
  return event;
}

function HookHarness({
  initialOpen,
  events,
}: {
  initialOpen: boolean;
  events: boolean[];
}) {
  const [open, setOpen] = useState(initialOpen);
  useSwipeDrawer(open, (next) => {
    events.push(next);
    setOpen(next);
  });
  return <div data-open={open ? "true" : "false"} />;
}

test("useSwipeDrawer opens from edge swipe and closes from left swipe on narrow screens", async () => {
  const restoreDom = installDom();
  const originalMatchMedia = window.matchMedia;
  const events: boolean[] = [];

  try {
    installMatchMedia(true);
    const view = await renderReact(<HookHarness initialOpen={false} events={events} />);
    await flushReact();

    await dispatchDocumentEvent(touchEvent("touchstart", { clientX: 10, clientY: 20 }));
    await dispatchDocumentEvent(touchEvent("touchend", { clientX: 100, clientY: 22 }));
    await flushReact();

    assert.deepEqual(events, [true]);
    assert.equal(view.container.firstElementChild?.getAttribute("data-open"), "true");

    await dispatchDocumentEvent(touchEvent("touchstart", { clientX: 120, clientY: 20 }));
    await dispatchDocumentEvent(touchEvent("touchend", { clientX: 30, clientY: 24 }));
    await flushReact();

    assert.deepEqual(events, [true, false]);
    assert.equal(view.container.firstElementChild?.getAttribute("data-open"), "false");

    await view.unmount();
  } finally {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    });
    restoreDom();
  }
});

test("useSwipeDrawer ignores non-eligible and mostly vertical swipes", async () => {
  const restoreDom = installDom();
  const originalMatchMedia = window.matchMedia;
  const events: boolean[] = [];

  try {
    installMatchMedia(true);
    const view = await renderReact(<HookHarness initialOpen={false} events={events} />);
    await flushReact();

    await dispatchDocumentEvent(touchEvent("touchstart", { clientX: 80, clientY: 20 }));
    await dispatchDocumentEvent(touchEvent("touchend", { clientX: 170, clientY: 24 }));
    await dispatchDocumentEvent(touchEvent("touchstart", { clientX: 10, clientY: 20 }));
    await dispatchDocumentEvent(touchEvent("touchend", { clientX: 40, clientY: 140 }));
    await flushReact();

    assert.deepEqual(events, []);
    assert.equal(view.container.firstElementChild?.getAttribute("data-open"), "false");

    await view.unmount();
  } finally {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    });
    restoreDom();
  }
});

test("useSwipeDrawer stays inactive on desktop widths", async () => {
  const restoreDom = installDom();
  const originalMatchMedia = window.matchMedia;
  const events: boolean[] = [];

  try {
    installMatchMedia(false);
    const view = await renderReact(<HookHarness initialOpen={false} events={events} />);
    await flushReact();

    await dispatchDocumentEvent(touchEvent("touchstart", { clientX: 10, clientY: 20 }));
    await dispatchDocumentEvent(touchEvent("touchend", { clientX: 100, clientY: 20 }));
    await flushReact();

    assert.deepEqual(events, []);
    assert.equal(view.container.firstElementChild?.getAttribute("data-open"), "false");

    await view.unmount();
  } finally {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    });
    restoreDom();
  }
});
