import assert from "node:assert/strict";
import test from "node:test";

import {
  countSubmittedUserMessages,
  isUnattendedInputLocked,
  nextUnattendedInputLockBaseline,
} from "./chat-view";

test("countSubmittedUserMessages ignores slash commands", () => {
  assert.equal(
    countSubmittedUserMessages([
      { kind: "user", content: "/help" },
      { kind: "user", content: "build status" },
      { kind: "assistant", content: "ok" },
    ]),
    1,
  );
});

test("unattended toggle in an existing session waits for the next user message", () => {
  const baseline = nextUnattendedInputLockBaseline({
    previousSessionId: "session-1",
    sessionId: "session-1",
    previousUnattended: false,
    sessionUnattended: true,
    previousBaseline: null,
    submittedUserMessageCount: 2,
  });

  assert.equal(baseline, 2);
  assert.equal(isUnattendedInputLocked(true, 2, baseline), false);
  assert.equal(isUnattendedInputLocked(true, 3, baseline), true);
});

test("existing unattended sessions still lock after a submitted message already exists", () => {
  const baseline = nextUnattendedInputLockBaseline({
    previousSessionId: "session-1",
    sessionId: "session-2",
    previousUnattended: false,
    sessionUnattended: true,
    previousBaseline: null,
    submittedUserMessageCount: 4,
  });

  assert.equal(baseline, 0);
  assert.equal(isUnattendedInputLocked(true, 4, baseline), true);
});
