// 3.9.9 (Sam's pick B): an event marked the exam. The plan keeps the mark
// (kind: "exam", nothing else) and a follower's board offers it as theirs.
import { describe, expect, it } from "vitest";
import { person } from "./helpers";

const UNITS = [{ id: "a", name: "Lecture 12", opens: "2026-11-02", tags: ["C::12"], n: 84 }];

async function save(who: Awaited<ReturnType<typeof person>>, events: unknown[]) {
  const made = await who.call("POST", "/plans", { name: "Heme-Onc", deck: "Big Step 1" });
  return who.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Big Step 1", units: UNITS, events } });
}

describe("an event marked the exam", () => {
  it("is kept with its mark, and a plain event stays plain", async () => {
    const priya = await person("priya");
    const put = await save(priya, [
      { id: "q", day: "2026-11-20", name: "Heme quiz" },
      { id: "x", day: "2026-12-12", name: "Heme-Onc block exam", kind: "exam" },
    ]);
    expect(put.status).toBe(200);
    const got = await priya.call("GET", `/plans/${put.body.id}`);
    expect(got.body.doc.events).toEqual([
      { id: "q", day: "2026-11-20", name: "Heme quiz" },
      { id: "x", day: "2026-12-12", name: "Heme-Onc block exam", kind: "exam" },
    ]);
  });

  it("takes no other kind and no other field", async () => {
    const priya = await person("priya2");
    expect((await save(priya, [{ id: "x", day: "2026-12-12", name: "Exam", kind: "quiz" }])).status).toBe(400);
    expect((await save(priya, [{ id: "x", day: "2026-12-12", name: "Exam", kind: "exam", big: true }])).status).toBe(400);
  });
});
