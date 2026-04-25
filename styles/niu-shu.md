# Style A: Uncle Niu (牛叔说电影)

## Mission

This is not a plot summary. It is an **audience-retention machine**. Every rule below exists to serve three jobs, in order:

1. **Hook the viewer in the first 10 seconds.** If the opening is not the single most shocking, funniest, or most visceral moment of the movie, you have failed. Front-load the best scene — always.
2. **Cover the whole story in 7-12 minutes.** The viewer leaves feeling they've seen the movie. No cliffhangers, no "watch it yourself for the ending." Start → climax → ending, all included.
3. **Keep them watching the whole way.** Plant a re-hook (twist, shock, laugh, absurd image) every 60-90 seconds. A flat chronological retelling loses viewers at 45 seconds. Uncle Niu's deadpan sarcasm, pseudo-idioms, and nonsense literature are the tools — use them constantly.

**Perspective:** Third-person omniscient, detached narrator
**Tone:** Deadpan, fast-paced, highly sarcastic — *tuned to the movie's genre* (see Section 5.5)
**Target Duration:** 7-12 minutes
**Character-count Window:** ~1,800-2,800 Chinese characters — calibrated for this style's dense, fast-paced delivery (long sentences, minimal breath pauses, ~240-260 chars/min via Qwen3-TTS Voice Clone on the Niu Shu base voice). Different styles will need different windows; see `_style_contract.md` §4 #5.
**Language:** Chinese (Mandarin) by default; English adaptation supported

> **Style pairing:** This is the *external observer* style — detached, sarcastic. For the intimate confessional alternative, see [`first-person-pov.md`](first-person-pov.md). The two styles have **opposite rules** on character naming (archetypes vs. original names) and narrator stance (sarcastic vs. sincere) — do not mix them within a single script.

---

## 1. Opening Hook (开头钩子) — The Single Most Important Rule

The first 10 seconds decide whether the viewer scrolls away. Everything else in this style is secondary. Nail this.

### The Front-Load Rule

**RULE:** The hook is NOT the opening scene of the movie. The hook is the **single most attention-grabbing moment anywhere in the movie**, pulled out of sequence and placed in the first 10 seconds of the review. After the hook, rewind: `故事要从三天前说起...`

If the movie opens slow, skip it. If the juiciest moment is the third-act twist, open with a teaser of it (without spoiling the mechanism), then rewind.

### Finding the Best Hook — Ranking Criteria

Scan the whole movie for candidate hook moments. Rank them by these criteria and use the top one:

1. **性暗示 (Sexual tension / taboo)** — suggestive, transgressive, not explicit
2. **犯罪与谋杀 (Crime & murder)** — corpses, heists, violence, blood
3. **身份/身体冲击 (Identity or bodily shock)** — surgery gone wrong, transformation, reveal that someone isn't who you thought
4. **冲突与矛盾 (Conflict & impossibility)** — betrayal mid-kiss, friend turns enemy, impossible setup
5. **悬念 (Pure suspense)** — unanswered question that forces the viewer to keep watching

### The 注意看 Formula

```
注意看，这个[descriptor]叫[archetype name]，[shocking/intriguing situation]
```

### Strong Hook Examples

- `注意看，这个男人叫小帅，他刚刚把一具尸体塞进了后备箱`
- `眼前这个女人叫小美，她和她的男朋友小帅，就在刚刚，亲手杀了自己的邻居`
- `注意看，这个看起来人畜无害的小女孩，手里正拿着一把沾满鲜血的刀`
- `注意看，这个男人叫小帅，他刚刚发现自己怀孕了，而他是个一米八五的肌肉猛男`

### Hook Failure Modes (what NOT to open with)

- The movie's literal opening scene if it's slow exposition
- Establishing shots of the setting
- Character backstory / "it was a normal day"
- Anything that takes more than one sentence to explain
- Anything that requires context the viewer doesn't have yet

### The Rewind Transition

After the hook, rewind with one of:
- `故事要从三天前说起...`
- `要弄明白这是怎么回事，咱们得把时间拉回到一个月之前`
- `他怎么走到这一步的？这事还得从头说起`

Keep the rewind transition to a single line — do not linger before returning to chronological narration.

---

## 2. Character Archetype Table (角色代号表)

**RULE: Original character names are FORBIDDEN.** Every character must be assigned an archetype name from this table. This is non-negotiable — it is the defining feature of this style, and also does two jobs at once:
1. **Cognitive load reduction** — the viewer doesn't have to remember unfamiliar foreign names
2. **Instant comic coloring** — `小帅` is funnier than `John`, `丧彪` is funnier than `Viktor`

### Primary Archetypes

| Archetype | Chinese | Pinyin | Assign To |
|-----------|---------|--------|-----------|
| Xiaoshuai | 小帅 | xiǎo shuài | Default male protagonist — the main guy |
| Xiaomei | 小美 | xiǎo měi | Default female protagonist — the main girl |
| Dazhuang | 大壮 | dà zhuàng | Muscular, physically strong, or tough male character |
| Sangbiao | 丧彪 | sàng biāo | Primary villain or antagonist |
| FBL | 佛波勒 | fó bō lè | Any law enforcement: police, FBI, agents (deliberate mispronunciation of FBI) |
| Xiakalami | 小卡拉米 | xiǎo kǎ lā mǐ | Unimportant extras, cannon fodder, nobodies (Dongbei dialect slang) |
| Qiantiaoshu | 千条叔 | qiān tiáo shū | Experienced older male — mentor, father figure, grizzled veteran |
| Huzige | 胡子哥 | hú zi gē | Any bearded male character |
| Dapiaoliang | 大漂亮 | dà piào liang | Attractive secondary character (either gender) |
| Jinfamei | 金发妹 | jīn fà mèi | Any blonde female character |
| Qiantiaojie | 千条姐 | qiān tiáo jiě | Experienced older female — female version of 千条叔 |

### Secondary Archetypes (for larger casts)

| Archetype | Chinese | Assign To |
|-----------|---------|-----------|
| Gangdan | 钢蛋 | Secondary male — replacing a Western male name |
| Cuihua | 翠花 | Secondary female — replacing a Western female name |
| Xiaobai | 小白 | Naive, innocent, or inexperienced character |
| Daqiang | 大强 | Strong-willed or aggressive supporting male |
| Dashan | 大山 | Quiet, reliable, mountain-of-a-man type |
| Azhen | 阿珍 | Generic supporting female |
| Aqiang | 阿强 | Generic supporting male |
| Dameili | 大美丽 | Second attractive female if 大漂亮 is taken |

### Assignment Rules

1. **Map by role, not appearance.** The male lead is always 小帅, even if he's ugly. The female lead is always 小美, even if she's plain.
2. **One archetype per character.** Once assigned, use consistently throughout the script.
3. **Introduce on first mention.** When a character first appears, introduce them with their archetype: `这时候，一个满脸胡子的男人走了过来，我们叫他胡子哥`
4. **Groups get collective names.** A squad of soldiers → `一群小卡拉米`. A pair of cops → `两个佛波勒`.
5. **Max ~8 named characters.** If the movie has more, merge minor roles into 小卡拉米 or skip them entirely. More than 8 archetypes = viewer gets lost.

---

## 3. Narrative Structure (叙事结构)

Four-act structure scaled to the target duration. Characters below are for a ~10-minute (2,400-char) script — scale linearly for 7-12 min.

| Act | Minutes | Chars | Job |
|-----|---------|-------|-----|
| 1 - Hook + Setup | ~2 | ~480 | Open with the front-loaded hook, rewind, introduce 小帅/小美 and the inciting incident |
| 2 - Escalation | ~3 | ~720 | Obstacles stack, villain enters, relationships form/break, build toward midpoint twist |
| 3 - Climax + Twist | ~3 | ~720 | Biggest reveal and confrontation — deploy maximum information density and 废话文学 |
| 4 - Resolution + Outro | ~2 | ~480 | Resolve, brief sarcastic verdict, sign off |

### Act-level non-negotiables

- **Act 1 must contain the hook.** No exceptions.
- **Every act must contain at least one re-hook.** (See Section 4 — Re-engagement Rhythm.)
- **Act 4 must contain the actual ending of the movie.** Uncle Niu style tells the complete story — never "想知道结局的自己去看" cop-outs.

---

## 4. Re-engagement Rhythm (留人节奏)

The hook gets them to watch. This keeps them watching.

**RULE:** A re-engagement beat must occur every **60-90 seconds** of narration (roughly every ~180-270 characters). If three consecutive paragraphs are flat plot summary, the viewer leaves.

### Re-engagement Beat Types (mix and match)

| Beat | Function | Frequency budget per script |
|------|----------|-----------------------------|
| **注意看 re-hook** | Redirect attention to a crucial detail | 3-5 |
| **沙雕吐槽 (Sarcastic commentary)** | Narrator briefly editorializes | 3-5 |
| **废话文学 (Nonsense literature)** | Deadpan absurd tautology | 2-3 |
| **假成语 (Pseudo-idiom)** | Fake classical Chinese gravitas | 1-2 |
| **Shock beat** | Unexpected violence/twist/reveal | 2-3 |
| **Dialogue punch** | A single quoted line delivered as a drop | 2-3 |

Distribute these across acts — do not cluster them all in Act 3. The viewer who makes it past minute 4 still needs a reason to stay for minute 5.

### The 90-Second Self-Check

When drafting, insert a mental checkpoint every ~250 characters and ask: *"Why would the viewer still be watching after this sentence?"* If the answer is "because I haven't finished the plot," insert a re-engagement beat before moving on.

---

## 5. Tone & Voice Rules (语气规则)

### Core Principle: Deadpan Sarcasm

The narrator tells the most absurd, violent, or emotional events with the same flat, matter-of-fact delivery. Never express genuine shock or emotion. Everything is narrated as if reading a grocery list.

**DO:** `小帅二话不说，掏出一把枪就把丧彪给崩了，然后若无其事地去吃了碗面`
**DON'T:** `天哪！小帅竟然开枪了！这太令人震惊了！！！`

### 废话文学 (Nonsense Literature / Redundant Phrasing)

A signature comedy technique — state the painfully obvious in a pseudo-profound way.

**Examples:**
- `这个长得像小女孩的小女孩，其实就是一个小女孩`
- `在小帅死了之后，他就不再活着了`
- `毫无疑问，这是一个毫无疑问的事实`
- `经过一番激烈的思想斗争，小帅决定不斗争了`

**Usage:** 2-3 times per script at moments of maximum absurdity. Don't overuse — it loses punch.

### Pseudo-Idioms (假成语)

Invent fake classical Chinese phrases that sound authoritative but mean nothing, or twist real idioms into nonsense.

**Examples:**
- `正所谓饮恨西北，小帅这一走就再也没回来` (饮恨西北 is not a real idiom)
- `古人云：事出反常必有妖，妖出反常必有事` (circular logic)

**Usage:** 1-2 per script maximum. Best placed before a dramatic beat.

### Information Density

- Maximize plot per sentence. Every sentence should advance the story OR land a joke OR deepen suspense.
- Cut all filler: no "我们知道", "大家可以看到", "其实在这里" type padding
- Acceptable pacing: ~4-5 plot beats per minute

### Sarcastic Commentary

The narrator occasionally breaks from plot summary to editorialize — but always briefly and with deadpan delivery.

**Examples:**
- `不得不说，小帅的智商确实感人`
- `到这里，相信观众已经猜到了结局——没错，你猜错了`
- `这段剧情有多离谱呢，反正导演自己可能都不信`

### 5.5 Genre Modulation — Tune the Voice to the Movie

The baseline is deadpan sarcasm, but the *weight* and *flavor* of that sarcasm must bend toward the movie's genre. A flat one-register voice on every movie is boring. Use this table:

| Movie Genre | Voice Tuning | Tools to Lean On | Tools to Pull Back |
|-------------|--------------|------------------|--------------------|
| **Comedy / Absurd** | Maximum sarcasm, maximum 废话文学 | 废话文学, 假成语, dialogue punches | Shock beats (the movie already provides them) |
| **Thriller / Horror** | Deadpan dread — describe violence like weather | Shock beats, 注意看 re-hooks, withholding | 废话文学 (undercuts tension) |
| **Action / Crime** | Rapid-fire, casual about violence | Information density, dialogue punches, sarcastic verdicts | Slow philosophical beats |
| **Drama / Tragedy** | Cut sarcasm with occasional sincerity at climax | Sarcastic commentary on characters' choices, 假成语 | Comic tautologies at the emotional peak |
| **Romance** | Skeptical of the romance itself | Sarcastic commentary, pseudo-idioms mocking love tropes | Sincere endorsement |
| **Sci-Fi / Fantasy** | Demystify the premise with mundane framing | 废话文学 ("原来外星人，其实就是外星的人"), archetype reductions | Explaining the lore seriously |

The moviereviewer who does a horror movie in the same tone as a romcom loses the audience who came for the horror. **Register must match expectations.**

### 5.5b Genre Visual Focus — which scene types dominate the hero-clip budget

Tonal matching isn't enough. The **visual footage** must also skew toward what the audience came for. Rule: a target fraction of your `[SCENE]` markers must point at genre-priority footage, regardless of what the narration literally describes.

| Genre | Priority visual | Minimum clip budget | What can be deprioritized |
|-------|-----------------|---------------------|----------------------------|
| **Action / fight** | Combat shots, impacts, power reveals | **≥40% of total clips** | Talking-head exposition, establishing shots |
| **Horror** | Jump scares, cursed imagery, gore | ≥35% | Daytime normalcy scenes |
| **Thriller / suspense** | Reveals, building dread, close calls | ≥30% | Over-explanation scenes |
| **Romance** | Emotional close-ups, touching, looks | ≥30% | Action beats |
| **Drama / tragedy** | Tear-worthy faces during emotional dialogue | ≥30% | Plot-mechanical scenes |
| **Comedy / absurd** | Reaction shots, absurd visuals, "how did we get here" shots | ≥35% | Straight-faced exposition |
| **Supernatural / fantasy** | Power demonstrations, creature reveals | ≥30% | World-building narration |
| **Crime / heist** | The heist/kill execution, tension moments | ≥30% | Backstory |

**B-roll cross-cuts — how to hit the budget when narration doesn't match.**

When the narration literally describes something non-priority (e.g., "千条叔给小帅的任务很明确" — a teacher explaining to a student), you MUST cross-cut to priority footage during that narration instead of showing a teacher-student talking-head.

Syntax for the script — multiple timestamps per narration block:

```
[SCENE: 00:19:38-00:19:48]                          # primary — matches narration literal
[BROLL: 01:11:40-01:11:45, 01:20:00-01:20:05]       # cross-cuts, rotated during narration
千条叔给小帅的任务很明确：
接受小美的诅咒，
一点一点灌进刀身里...
```

`stage5_render_video.py` cycles the primary + B-roll clips to fill the narration duration. The viewer sees a talking-head-intro-shot then two quick fight flashes, even though the narration is pure exposition.

**Applying this rule to JJK0 (for reference):** the current niu-shu draft has ~14 of 57 clips (~25%) as actual combat — under the 40% action target. Act 1's 11 flashback/setup clips should be cut or cross-cut with fight B-roll. Act 2's exposition (class intros, training) should add fight B-roll from act 2's mission scenes. Fix: insert `[BROLL: ...]` markers for at least half the non-fight clips.

---

## 6. Transition Phrases (过渡短语)

Use these to maintain pace and connect scenes. Vary them — don't repeat the same one consecutively.

### Time Jumps
| Phrase | Meaning | Usage |
|--------|---------|-------|
| 下一秒 | The next second | Immediate action — something happens right now |
| 就在这时 | Right at this moment | Interrupt current action with new event |
| 时间来到了第二天 | Time moves to the next day | Skip forward |
| 三天后 / 一个月后 | Three days / one month later | Larger time skip |

### Surprise & Reversal
| Phrase | Meaning | Usage |
|--------|---------|-------|
| 却没想到 | But [they] didn't expect | Surprise twist — the plan fails |
| 不出意外的话要出意外了 | If nothing unexpected happens, something unexpected will | Ironic foreshadowing (signature phrase) |
| 正当所有人以为事情结束的时候 | Just when everyone thought it was over | False resolution → new complication |
| 但事情远没有这么简单 | But things are far from that simple | Signal deeper conspiracy or twist |

### Narrative Control
| Phrase | Meaning | Usage |
|--------|---------|-------|
| 注意看 | Pay attention | Re-hook — draw focus to important detail (reuse throughout, not just opening) |
| 按下不表 | Set aside for now | Borrowed from 评书 (traditional storytelling); pause one plotline to switch to another |
| 我们先把时间拉回到… | Let's pull time back to… | Flashback |
| 原来 | It turns out | Reveal — information the audience didn't have |

---

## 7. Plot Compression Rules (剧情压缩)

A 2-hour movie compressed to 7-12 minutes. Compression decisions serve the three Mission goals: preserve the hook, cover the whole plot, and keep engagement alive.

1. **Cut subplots ruthlessly.** Keep only the main plot arc. Romance subplots are cut unless they drive the main conflict.
2. **Merge minor characters.** If three characters serve the same narrative function, combine them into one archetype.
3. **Skip establishing shots.** Don't describe scenery, costumes, or atmosphere unless it's plot-critical.
4. **Summarize montages.** Training sequences, travel scenes, and "passage of time" montages get one sentence maximum.
5. **Preserve twists and reveals.** These are the payoff — compress the setup, but never skip the twist.
6. **Preserve the ending.** Uncle Niu style tells the COMPLETE story including the ending. The viewer should feel they've "watched" the whole movie.
7. **Preserve any scene strong enough to be the hook.** If you demoted it from opener to act-3, still give it full weight when it arrives.

### Compression Priority

| Keep (full detail) | Summarize (1-2 sentences) | Cut entirely |
|--------------------|---------------------------|--------------|
| Opening incident | Character backstories | Establishing shots |
| Key confrontations | Travel/transition scenes | Romance filler |
| Plot twists & reveals | Training montages | Repeated beats |
| Climax | World-building exposition | Dream sequences (unless plot-critical) |
| Ending/resolution | Side character arcs | Musical numbers |
| Hook-candidate scenes | | |

---

## 8. Closing (结尾)

End the script with one of these patterns:

### Option A: Commentary Close
Brief opinion on the movie, then sign off.
```
这部电影告诉我们一个道理：[sarcastic moral]。好了，这就是今天的故事，我们下期再见。
```

### Option B: Question Close
Pose a question to the audience.
```
你觉得小帅最后的选择是对是错？欢迎在评论区告诉我。我们下期再见。
```

### Option C: Callback Close
Reference the opening hook.
```
还记得开头那个[reference to hook]吗？现在你知道答案了。我们下期再见。
```

All closings MUST end with: `我们下期再见` (See you next time).

---

## 9. Hard Constraints (红线)

These rules cannot be broken under any circumstances:

1. **Open with the best scene in the movie, not the first scene.** Front-load always. (See Section 1.)
2. **No original character names.** Use archetypes only. No exceptions.
3. **No spoiler warnings.** This style tells the complete plot. No "spoiler alert" disclaimers.
4. **No first-person narration.** Always third-person omniscient. Never "I think" or "I feel" from the narrator.
5. **No moral lectures.** The narrator is amused, not outraged. No "this movie teaches us the importance of..." sincerity.
6. **No exclamation-mark spam.** Maximum 3 exclamation marks in the entire script. The tone is deadpan.
7. **No English words in the Chinese script.** Translate or localize everything. FBI → 佛波勒, not "FBI".
8. **Must include the complete ending.** Don't cut off with "watch the movie to find out."
9. **Script must open with 注意看.** No exceptions.
10. **Re-engagement beat every 60-90 seconds.** No flat stretches longer than ~270 characters.
11. **Duration must land in 7-12 min (~1,800-2,800 chars).** Shorter loses the "whole story" feel; longer loses retention.

---

## 10. Script Output Format

This style file is consumed by Stage 2's **writer pass**. Writer-pass output uses `[BEAT N]` markers, not timestamps. The grounder pass replaces each `[BEAT N]` with a `[SCENE …]` marker — that contract is owned by `app/pipeline/stage2_generate_script.py`'s grounder prompt, not this style file.

The structural skeleton:

```
[TITLE] 注意看，[short hook summary that becomes the video title]

[HOOK]
[BEAT 1]
注意看，这个男人叫小帅...

[ACT 1 - SETUP]
[BEAT 2]
(narrative text)
[BEAT 3]
(narrative text — Act 1 totals ~480 characters)

[ACT 2 - ESCALATION]
[BEAT N]
(narrative text — Act 2 totals ~720 characters)

[ACT 3 - CLIMAX]
[BEAT N]
(narrative text — Act 3 totals ~720 characters)

[ACT 4 - RESOLUTION]
[BEAT N]
(narrative text — Act 4 totals ~480 characters)

[CLOSING]
[BEAT N]
我们下期再见。
```

**Rules for markers:**
- Each beat is one breathable spoken sentence or a short paragraph (~30-90 Chinese characters). Aim for 30-60 beats total across the script.
- Structural markers `[TITLE]`, `[HOOK]`, `[ACT N]`, `[CLOSING]` and `[BEAT N]` markers are stripped from the final voiceover but kept for downstream stages and human review.
- Do NOT emit `[SCENE …]` or `[BROLL]` markers in the writer pass — the grounder pass adds those after evidence-based alignment to the SRT and visual-segment indexes.

---

## 11. Archetype Assignment Workflow

Before writing the script, the agent MUST:

1. **Read the subtitle file** to identify all named characters
2. **Rank characters** by screen time / dialogue frequency
3. **Assign archetypes** using the table in Section 2, following the assignment rules
4. **Identify hook candidates** — scan the full plot for the top 3 most attention-grabbing moments (by Section 1 criteria), and pick one
5. **Output a mapping table** for user review before proceeding:

```
角色对照表:
John → 小帅 (male protagonist)
Sarah → 小美 (female protagonist)
Viktor → 丧彪 (villain)
Detective Mills → 佛波勒 (law enforcement)
Old Man Jenkins → 千条叔 (experienced elder)
Henchman 1, 2, 3 → 小卡拉米 (extras)

钩子候选 (ranked):
1. [00:47:20] John opens the trunk — a body falls out. [SELECTED]
2. [01:12:05] Sarah pulls the gun on her own father.
3. [00:03:15] Opening — Viktor executes a witness.

选定类型修饰 (Genre modulation): Crime thriller → deadpan dread, dense pacing, minimal 废话文学.
```

The user may override archetype assignments, hook selection, or genre modulation before the script is generated.
