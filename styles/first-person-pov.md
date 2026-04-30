# Style B: First-Person Protagonist POV (第一人称)

## Mission

This is not a plot retelling. It is a **confession that the viewer cannot stop listening to**. Every rule below exists to serve three jobs, in order:

1. **Hook the viewer in the first 10 seconds with the protagonist's most visceral moment.** First-person has a structural advantage over third-person — the voice is intimate, confessional, taboo. Exploit that. Open with the most personal, bodily, violating, or identity-shaking moment of the movie, *from the protagonist's mouth*. If the viewer is not hooked by second 10, you have failed.
2. **Cover the whole story in 7-12 minutes.** The viewer leaves feeling they've lived through the movie alongside the protagonist. Start → reveal → ending, all included. No cliffhangers.
3. **Keep them watching through emotional rhythm.** This style does not use sarcasm or comedy to re-engage — it uses **revelation, violation, and vulnerability**. Plant a new interior shock (an "我那时候才知道...", a dialogue punch, a dread reveal) every 60-90 seconds.

**Perspective:** First-person ("我") — narrated by the **protagonist**, in their own voice
**Tone:** Emotional, immersive, confessional — *tuned to the movie's genre* (see Section 5.5)
**Target Duration:** 7-12 minutes
**Character-count Window:** ~1,800-2,800 Chinese characters — **provisional**, copied from Niu Shu and not yet re-calibrated. This style uses short breathable sentences (majority under 15 chars, see §6) with frequent line-break pauses, so the spoken time per character is longer than Niu Shu's; the upper end of this window may overshoot 12 min. Recalibrate against the first real TTS render and tighten this range. See `_style_contract.md` §4 #5.
**Language:** Chinese (Mandarin) by default; English adaptation supported

> **Style pairing:** This is the *intimate confessional* style. For the detached sarcastic alternative, see [`niu-shu.md`](niu-shu.md). The two styles have **opposite rules** on character naming (original names vs. archetypes) and narrator stance (sincere vs. sarcastic) — do not mix them within a single script.

---

## 1. Opening Hook (开头钩子) — The Single Most Important Rule

First-person POV's secret weapon is **intimacy**. The viewer is not watching a review — the viewer is overhearing someone's private testimony. A confessional hook beats a descriptive hook every time.

### The Front-Load Rule

**RULE:** Do not start at the movie's opening. Scan the whole plot for the protagonist's most visceral, private, or transgressive moment, and open there. After the hook, rewind.

The "best" opening is almost never the movie's first scene. It is more likely:
- The protagonist waking up changed (surgery, transformation, post-trauma)
- The protagonist realizing they have been watched / violated / betrayed
- The protagonist doing something shocking that they will later explain
- The protagonist saying something taboo out loud

### Finding the Best Hook — Ranking Criteria

Scan the whole movie for candidate first-person hooks. Rank and pick the top one:

1. **身体/身份危机 (Body or identity violation)** — waking up changed, pregnancy, surgery, discovering something wrong with one's own body, gender shift, possession
2. **被侵犯感 (Sense of violation)** — stalker revealed, trusted person betrayed them, private space invaded, secret exposed
3. **禁忌独白 (Taboo confession)** — the protagonist admitting something they shouldn't — a crime, a desire, an identity
4. **突兀的荒诞 (Sudden absurdity)** — world-swap, reincarnation memory, impossible reveal, "我一大男人居然怀孕了"
5. **冲突爆发点 (Conflict ignition)** — the protagonist mid-confrontation with no context yet

### Hook Patterns

#### Pattern A: Crisis In-Medias-Res
Drop into the worst moment mid-scene.
```
女医生在为我检查身体
我竟还觉得有点享受
本以为只是个小手术
可等我醒过来却觉得下面空荡荡的
```

#### Pattern B: Absurd / Impossible Statement
A one-line identity-bending hook that cannot be scrolled past.
```
在家做烘焙 揉着面团
突然一阵反胃吐了
我一大男人居然怀孕了
```

#### Pattern C: Fragment of Dialogue
A line the protagonist is mid-saying, no context yet — forces the viewer to wait for context.
```
我早跟你说过
我不是妖姬
也不是诗诗
我是姬姬
```

#### Pattern D: Violation Reveal
Drop in at the moment the protagonist discovers they've been watched / followed / invaded.
```
我随便看了下窗外
竟发现那个老头又在偷窥我
我忍无可忍叫上闺蜜上门质问
却被老头的话吓个半死
```

### Hook Failure Modes (what NOT to open with)

- A calm exposition of the protagonist's name / job / daily life (that comes *after* the hook — see Section 2)
- Scene-setting or atmosphere
- Backstory of anyone other than the protagonist
- Any line that takes more than 10 seconds to pay off
- Anything said by a third-person narrator — the protagonist must speak the hook

### The Rewind Transition

After the hook, rewind with one of:
- `事情要从[time marker]说起...`
- `说起我以前什么样...`
- `一切要从那个[adjective]的夜晚说起`

---

## 2. Self-Introduction (自我介绍)

**RULE:** Within the first ~30 seconds (roughly right after the hook + rewind transition), the protagonist introduces themselves: `我叫[name]`. This is the signature beat of the style and the emotional anchor that makes the rest of the story hit.

### Formula

```
我叫[name]
[one-line identity: job / role / defining trait]
[one-line life-before: what daily life looked like]
```

### Examples

```
我叫方慧
是一名电话接线员
独自在外地租房子住
日子过得简单又安静
```

```
我叫胡铁男
说起我以前什么样
人如其名
铁血直男
成功学大师
```

```
我叫姬姬
是香港一家精神病院的医生
同事们都叫我女魔头
大概因为我做事雷厉风行
```

### Rules

1. **Use the protagonist's original name.** No archetype mapping. Names carry the emotional weight here — the opposite of Uncle Niu style.
2. **Introduce the protagonist only.** Secondary characters are named when they first appear in the story, not pre-loaded.
3. **Keep it tight.** 3-6 lines maximum.
4. **If the protagonist has a name change mid-story** (alias, gender transition, reincarnation reveal), introduce them under the name they identify with *at the start*. The later name shift becomes a beat.

---

## 3. Protagonist Selection (主角选择)

Before writing the script, the agent MUST identify and commit to one protagonist.

### Selection Criteria (in order of importance)

1. **Emotional arc** — who changes the most from start to end? This style lives on transformation.
2. **Agency** — who makes the most story-driving decisions?
3. **Screen time** — who appears in the most scenes?
4. **Viscerality of their experience** — whose interior experience is most shocking, taboo, or compelling to narrate?

When #1 and #2-3 conflict (a reactive protagonist with more screen time than a driving side character), **prefer the emotional arc**.

### Output a Protagonist Pick for User Review

Before writing the script:

```
主角选择:
Selected: [Character Name] ([role])
Reason: [one-line justification — emotional arc / agency / screen time / viscerality]
Alternatives considered: [one or two runners-up, why rejected]
```

The user may override the selection before generation.

---

## 4. Narrative Structure (叙事结构)

Four-act structure scaled to the target duration. Characters below are for a ~10-minute (2,400-char) script — scale linearly for 7-12 min.

| Act | Minutes | Chars | Job |
|-----|---------|-------|-----|
| 1 - Hook + Intro + Setup | ~2 | ~480 | Front-loaded hook, self-intro `我叫...`, rewind to "before," inciting incident |
| 2 - Escalation | ~3 | ~720 | Complications, new relationships, wrong coping, withhold the twist |
| 3 - Reveal + Climax | ~3 | ~720 | Truth lands — from the protagonist's ignorance to awareness. Emotional peak. Defining choice. |
| 4 - Aftermath + Reflection | ~2 | ~480 | Resolve the external plot, then shift register into reflection (see Section 8) |

### Act-level non-negotiables

- **Act 1 must contain the `我叫[name]` self-introduction.** Non-negotiable.
- **Act 3 must contain the emotional peak.** This style's hook is emotional, not intellectual — the climax must *hurt* or *liberate*.
- **Act 4 must shift register.** The final ~100-200 characters must stop being narration and become reflection, image, or direct address. This shift is the closing signature. See Section 8.

---

## 5. Re-engagement Rhythm (留人节奏)

The intimate hook gets them to watch. **Interior revelation** keeps them watching.

**RULE:** A re-engagement beat must occur every **60-90 seconds** of narration (roughly every ~180-270 characters). If three consecutive paragraphs are flat chronological summary, the viewer leaves.

Unlike Uncle Niu, this style does not re-engage with jokes. It re-engages with **things the protagonist just realized, saw, felt, or was told**.

### Re-engagement Beat Types (mix and match)

| Beat | Function | Frequency budget per script |
|------|----------|-----------------------------|
| **Delayed realization** (`我才发现...`, `后来我才知道...`) | Retrospective shock drop | 3-5 |
| **Interior collapse** (`我彻底崩溃了`, `我心里...`) | Emotional peak marker | 3-4 |
| **Dialogue punch** | A single quoted line from another character, delivered as a drop | 3-5 |
| **Violation beat** | A new invasion, discovery, or betrayal | 2-3 |
| **Retrospective leak** (`而我并不知道...`) | Permitted narrator bleed — the protagonist knows now what they didn't know then | 2-3 max |
| **Sensory shock** | A physical image the protagonist cannot unsee | 2-3 |

### The 90-Second Self-Check

When drafting, every ~250 characters ask: *"What does the viewer learn or feel here that they didn't 20 seconds ago?"* If the answer is nothing, insert a reveal, a dialogue punch, or a violation beat before continuing.

---

## 6. Tone & Voice Rules (语气规则)

### Core Principle: Sincere Interiority

The protagonist is telling their story to you. No winking at the camera, no sarcasm about the plot, no editorializing from outside the character. Every line is what the protagonist thought, felt, or said *in that moment* or *looking back*.

**DO:** `我心里一下子暖了起来`
**DO:** `我彻底崩溃了 / 从头到尾都是爸妈在替我做决定`
**DON'T:** `不得不说，这个主角的智商确实感人` (that is Uncle Niu's voice, not the protagonist's)

### Interior Markers (signature phrases — use constantly)

| Marker | Function |
|--------|----------|
| 我心里... | Inner emotional state |
| 我以为... | Protagonist's assumption (usually wrong) |
| 我才发现... / 我才知道... | Delayed realization |
| 我吓得... | Fear reaction |
| 我彻底崩溃了 | Emotional breaking point |
| 我那时候... | Retrospective distance |
| 现在想想... / 现在回头想想... | Looking back from after the story |
| 后来我才... | Future knowledge bleeding into past narration |
| 而我并不知道... | Retrospective leak — protagonist didn't know, viewer now does |

### Short Sentence Discipline

Each line must be breathable — the viewer hears this as spoken narration, not read prose. Keep the majority of sentences **under 15 characters**. Use line breaks where a speaker would pause. This is the opposite of Uncle Niu's dense sentences.

Compare:
- NIU-SHU (dense): `小帅二话不说，掏出一把枪就把丧彪给崩了，然后若无其事地去吃了碗面`
- FIRST-PERSON (breathable):
  ```
  我没有多想
  掏出枪
  对着他扣下了扳机
  然后走出去
  吃了一碗面
  ```

### Dialogue Integration

Dialogue is woven inline (no quote marks), usually as alternating short lines between speakers. Do not introduce speakers with `他说` / `她说` if the speaker is obvious from context.

```
妈 我到底得了什么病啊
不是都说了吗
就包皮过长啊
真的吗
```

Use dialogue sparingly — 3-6 exchanges per act. Every dialogue block must carry plot weight or emotional weight; no small talk.

### Withholding Knowledge

The narrator only knows what the protagonist knows *at that point in the story*. Reveals must come as surprises to the protagonist, not as foreshadowed drops.

**DO:**
```
回屋后
我拿起手机开始找房子
准备赶紧搬走
可找着找着
头忽然一阵发晕
眼皮沉得撑不住
就这么昏了过去
而我并不知道
那时候一个男人
正从卫生间走出来
```

The `而我并不知道` line is the permitted exception — a single retrospective leak that signals "you, the viewer, get to see what I couldn't." Use at most 2-3 times in a script, only for crucial setup.

### 6.5 Genre Modulation — Tune the Voice to the Movie

The baseline is sincere interiority, but the *register* of that interiority must bend toward the movie's genre. A flat emotional monotone across every movie is boring. Use this table:

| Movie Genre | Voice Tuning | Tools to Lean On | Tools to Pull Back |
|-------------|--------------|------------------|--------------------|
| **Thriller / Stalker / Horror** | Short sentences. Dread. Withhold heavily. | Sensory shock, `而我并不知道` leaks, violation beats | Long retrospective reflection (kills tension) |
| **Trauma / Identity drama** | Raw, bodily, present-tense intensity | Interior collapse, bodily imagery, dialogue punches | Narrative distance — stay close to the skin |
| **Coming-of-age / Romance** | Vulnerable, tender, naive early → wiser late | `我心里...`, `我以为...` reversals, first-love imagery | Cynicism at the start |
| **Absurd / Comedy / World-swap** | Protagonist's **incredulity** carries the comedy | `我一大男人居然怀孕了`-style bluntness, straight-face reactions to absurdity | Direct jokes — let the absurdity speak |
| **Supernatural / Reincarnation** | Rational voice slowly cracking under impossible evidence | Retrospective leaks, mounting `我才知道` realizations | Explaining the lore up front |
| **Crime / Confession** | Morally ambivalent, matter-of-fact about the crime | Deadpan admissions, interior justifications | Apologies or self-pity |

The protagonist of a horror movie should sound afraid. The protagonist of a gender-swap comedy should sound indignant. **Register must match the movie's emotional gravity.**

---

## 7. Plot Compression Rules (剧情压缩)

A 2-hour movie compressed to 7-12 minutes, filtered through one person's eyes. Compression decisions serve the three Mission goals: preserve the hook, cover the whole plot, and keep engagement alive.

1. **Cut anything the protagonist didn't witness.** Scenes the protagonist wasn't present for can only be referenced as something they *later learned*. Never narrate them directly.
2. **Compress by emotional weight, not screen time.** A 5-minute movie scene that devastates the protagonist gets 3 paragraphs. A 15-minute action scene they observed passively gets 2 sentences.
3. **Preserve the protagonist's ignorance.** Don't pre-load information to make the plot cleaner. The story's tension lives in the gap between what the protagonist thinks and what is true.
4. **Preserve the ending.** Like Uncle Niu style, tell the complete story. Do not cut at a cliffhanger.
5. **Keep the interior.** If forced to choose between a plot beat and the protagonist's reaction to it, keep the reaction — that's why the viewer is here.
6. **Preserve any scene strong enough to be the hook.** If you demoted it from opener to mid-story, still give it full weight when it arrives.

### Compression Priority

| Keep (full interior detail) | Summarize (1-2 lines) | Cut entirely |
|-----------------------------|----------------------|--------------|
| Moments of realization | Scenes the protagonist only heard about | Scenes with no protagonist |
| Betrayals / violations | Travel / transitions | Pure exposition about side characters |
| Interior emotional peaks | Side character arcs | Establishing shots, world-building |
| Dialogue that changes the protagonist | Montages | Scenes that don't touch the protagonist's arc |
| The final choice | Background plot beats | Romantic/sexual detail beyond one line |
| Hook-candidate scenes | | |

---

## 8. Closing (结尾)

The ending is the style's second signature beat — alongside `我叫[name]`. It must **shift register** from chronological narration into reflection, image, or direct address. The last ~60-200 characters stop telling the story and start speaking *about* it.

### Option A: Philosophical Reflection
A lesson learned, spoken as a truth to the viewer.
```
真正的安全
从来不是锁好门窗就够了
而是需要我们
对自己心里那一点点不安
多一份在意
```

### Option B: Identity Consolidation
The protagonist names themselves at the end — often echoing the Section 2 self-introduction with new meaning.
```
我不再是那个孤身刺鬼的新娘
也不再是那个困惑不已的医生
我叫姬姬
我叫诗诗
我是每一个在绝境中
仍敢拔剑的人
```

### Option C: Blessing / Wish
Turn the ending outward to the audience.
```
愿每一个独自生活的人
都能被这个世界温柔以待
也都能拥有
保护好自己的力量
```

### Option D: Dark Image Close
For tragedies, end on a held image of the protagonist in their new state — no moral, no wish. Let the image do the work.
```
回到家我换上一身漂亮的裙子
画了浓妆
涂上口红
在房间里一个人转着圈跳舞
最后对着镜子
露出一个惨惨的笑
```

Unlike Uncle Niu style, **no signature sign-off** (`我们下期再见`) is required. The final image or reflection *is* the closing.

### Genre-Closing Fit

| Genre | Preferred Closing |
|-------|-------------------|
| Thriller / Horror | A or C — reflection or blessing, to give the viewer relief after dread |
| Trauma / Drama | D — dark image, or B if the protagonist survives intact |
| Coming-of-age | B — identity consolidation, the protagonist claims their new name |
| Comedy / World-swap | A with a touch of irony, or B on a warmer note |
| Crime / Confession | D — no redemption arc, let the image land |

---

## 9. Hard Constraints (红线)

These rules cannot be broken under any circumstances:

1. **Open with the protagonist's most visceral moment, not the movie's opening.** Front-load always. (See Section 1.)
2. **First-person throughout.** Every line is from the protagonist's POV. No third-person narration. No "he did / she did" for the protagonist.
3. **Use original character names.** No archetype mapping. (Opposite of Uncle Niu.)
4. **Must include `我叫[name]` self-introduction** within Act 1.
5. **No narrator commentary from outside the character.** No sarcasm about the plot, no "导演自己都不信" style asides.
6. **No spoiler pre-loading.** The protagonist does not know the twist before the story reveals it to them. (Retrospective leaks are capped at 2-3.)
7. **No `注意看` hook.** That is the Uncle Niu signature — using it here breaks the style.
8. **Include the complete ending.** No "想知道结局请看电影" cop-out.
9. **Register shift at close.** The final passage must shift from narration into reflection, image, or direct address.
10. **Short breathable sentences.** Majority of lines under 15 characters.
11. **Re-engagement beat every 60-90 seconds.** No flat stretches longer than ~270 characters.
12. **Duration must land in 7-12 min (~1,800-2,800 chars).**

---

## 10. Script Output Format

This style file is consumed by Stage 2's **single-pass planner-writer**. The planner picks visual anchors AND writes narration in one LLM call. Output uses `[ANCHOR ranges="..."]` markers — each anchor names one or more source-shot ranges, with the narration text below it bounded by `sum(range_seconds) × chars_per_second`.

The `我叫[name]` self-introduction (Section 2) lives **inside** `[ACT 1 - SETUP]` as the act's opening anchors — it is **not** a peer structural marker. The pipeline parser (`script_contract.py:STRUCTURAL_MARKER_RE`) recognizes only `[TITLE]`, `[HOOK]`, `[ACT N - …]`, and `[CLOSING]` as structural.

The structural skeleton:

```
[TITLE] [short hook summary that becomes the video title]

[HOOK]
[ANCHOR ranges="HH:MM:SS-HH:MM:SS"]
(in-medias-res opening, breathable lines from protagonist's POV)

[ACT 1 - SETUP]
[ANCHOR ranges="HH:MM:SS-HH:MM:SS"]
我叫[name]
[ANCHOR ranges="HH:MM:SS-HH:MM:SS"]
(establishing identity + "before" life)
[ANCHOR ranges="HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS"]
(rewind to beginning, inciting incident — Act 1 totals ~480 characters)

[ACT 2 - ESCALATION]
[ANCHOR ranges="..."]
(complications, relationships, wrong coping — Act 2 totals ~720 characters)

[ACT 3 - REVEAL + CLIMAX]
[ANCHOR ranges="..."]
(truth lands, emotional peak, choice — Act 3 totals ~720 characters)

[ACT 4 - AFTERMATH]
[ANCHOR ranges="..."]
(resolution — Act 4 totals ~300-400 characters)

[CLOSING]
(register shift: reflection / identity / blessing / dark image, ~100-200 characters)
NO [ANCHOR] — Stage 6 plays this passage over the most recent keyframe.
```

**Rules for markers:**
- Each `[ANCHOR]` is one breathable beat. This style favors short sentences (majority under 15 characters — see §6), so a single anchor's narration may contain a stanza of several short lines that together form one breath group.
- Each range stays inside ONE source shot (one `[shot:NNN]` from the timeline the planner is given). Range timestamps come from `[shot:NNN]` lines, never from `[srt:NNN]` lines.
- Each individual range duration ≤ 12s. Each anchor's total duration (sum of range durations) ≤ 12s.
- The closing chunk has narration but no `[ANCHOR]` — Stage 6 plays it over the most recent keyframe.
- Structural markers `[TITLE]`, `[HOOK]`, `[ACT N]`, `[CLOSING]` and the `[ANCHOR ...]` lines are stripped from the final voiceover but kept for downstream stages and human review.
- Aim for 30-60 anchors total across the script (this style's shorter sentences mean fewer chars per anchor; the count tracks the act-level char totals above).

---

## 11. Protagonist Selection Workflow

Before writing the script, the agent MUST:

1. **Read the subtitle file** and identify all named characters with dialogue
2. **Rank characters** by emotional arc + agency + screen time + viscerality
3. **Select one protagonist** using the Section 3 criteria
4. **Identify hook candidates** — scan the full plot for the top 3 most visceral / intimate / taboo moments from the protagonist's POV (by Section 1 criteria), and pick one
5. **Extract a voice reference** — locate 3-10 seconds of clean dialogue from the selected protagonist in the movie file. This is the TTS reference for `stage3_generate_audio.py` voice cloning.
6. **Output a protagonist pick + hook pick** for user review:

```
主角选择:
Selected: Yang Shinan / Shilan (intersex teen)
Reason: Highest emotional arc — the story's entire transformation happens to her. Full plot visible through her eyes.
Alternatives considered:
  - Dr. Li (antagonist) — rejected: no interior sympathy, villain POV would flatten the story
  - Mother — rejected: lower screen time, arc is reactive

钩子候选 (ranked):
1. [00:08:40] Shilan wakes from surgery, realizes her body has been changed without consent. [SELECTED]
2. [00:42:15] Discovery that her "antidepressants" were estrogen all along.
3. [01:05:30] Classroom outing — strangers treat her as a monster.

选定类型修饰 (Genre modulation): Trauma / identity drama → raw bodily intensity, stay close to the skin, dark-image close.

Voice reference: 00:12:34 - 00:12:41 (clean single-speaker dialogue)
```

The user may override protagonist, hook, or genre modulation before the script is generated.
