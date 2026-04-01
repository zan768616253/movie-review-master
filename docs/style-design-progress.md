# Style System Design — Progress Tracker

**Status:** Style A draft complete; Style B not started; Style C research in progress
**Last Updated:** 2026-04-01
**Next Step:** Install Whisper, transcribe audio files (Uncle Niu + Xiaodao), refine style files with real transcript data; brainstorm Style B

---

## What We're Designing

The style definition files that tell Claude how to generate movie review scripts in specific narrative styles:
- `styles/niu-shu.md` — **Style A: Uncle Niu (牛叔说电影)** — third-person omniscient, deadpan, sarcastic
- `styles/first-person-pov.md` — **Style B: First-Person Protagonist POV** — emotional, immersive (not started)
- `styles/xiaodao.md` — **Style C: Xiaodao (小岛电影)** — warm narrator, sentimental, philosophical (research phase)

Previous session focused on Style A. This session began research on Style C.

---

## Research Completed

### Uncle Niu YouTube Videos Analyzed

| # | Video ID | Title | Channel |
|---|----------|-------|---------|
| 1 | Izm5XmOvi9k | 叛逆少女穿越回35年前，直面杀手，拯救母亲与小镇！ | 牛叔说电影 (main) |
| 2 | DGMsAjWBUas | 【牛叔】恐龙灭绝的原因，99年事件的真相，人类距离灭绝只差一次大冲撞 | 牛叔说电影 (main) |
| 3 | A-dvs069Wl8 | 【牛叔】燃烧！高校争霸武斗篇，铃兰双雄大对决，谁才是最后的王者 | 牛叔说电影 (main) |
| 4 | -czN5o7dHlw | 【牛叔】戲說電影《綠巨人浩克》文縐縐的綠胖有點太慢啦！ | 副频道【牛叔说电影】(sub) |
| 5 | JBuD4FovNwM | 【牛叔】惊天大新闻！《黑衣纠察队》05 超人类居然人为制造？女版狼叔登场 | 牛叔说电影 (main) |
| 6 | fKHD4m8UKqM | 【牛叔】戏说电影《午夜夜幕》特种部队内部的勾心斗角 | 副频道【牛叔说电影】(sub) |
| 7 | 08dJ3x9ufCk | 【牛叔】爽就完了，退役兵王为救小孩，1人横扫一个国家的军队，结局太舒服 | 牛叔说电影 (main) |

### Character Archetype Table (from web research)

| Archetype | Chinese | Role | When to Use |
|-----------|---------|------|-------------|
| Xiaoshuai | 小帅 | Handsome male lead | Default male protagonist |
| Xiaomei | 小美 | Beautiful female lead | Default female protagonist |
| Dazhuang | 大壮 | Muscular/strong male | Physical/tough male lead |
| Sangbiao | 丧彪 | Villain | Any antagonist |
| FBL | 佛波勒 | Law enforcement | Police, FBI, agents (deliberate mispronunciation) |
| Xiakalami | 小卡拉米 | Extras/nobodies | Unimportant side characters (Dongbei dialect) |
| Qiantiaoshu | 千条叔 | Experienced elder | Middle-aged men with backstory |
| Huzige | 胡子哥 | Bearded man | Any bearded character |
| Dapiaoliang | 大漂亮 | Attractive support | Secondary attractive characters |
| Gangdan | 钢蛋 | Foreign male name sub | Replacing Western male names |
| Cuihua | 翠花 | Foreign female name sub | Replacing Western female names |
| Jinfamei | 金发妹 | Blonde girl | Any blonde female character |
| Qiantiaojie | 千条姐 | Experienced woman | Female version of 千条叔 |
| Additional | 小白, 大强, 大山, 阿珍, 阿强, 大美丽 | Various supporting | Context-dependent |

### Opening Hook Pattern

- **Mandatory opener:** "注意看" (Pay attention)
- **Formula:** "注意看，这个男人叫小帅，他..." or "眼前这个女人叫小美，她和她的男朋友小帅，就在刚刚……"
- Hooks prioritize: 性暗示、犯罪与谋杀、冲突与矛盾 (sexual innuendo, crime/murder, conflict/contradiction)

### Transition Phrases

| Phrase | Meaning | Usage |
|--------|---------|-------|
| 注意看 | Pay attention | Reused throughout, not just opening |
| 下一秒 | The next second | Quick time jump |
| 却没想到 | But didn't expect | Surprise twist |
| 不出意外的话要出意外了 | If nothing unexpected happens, something unexpected will | Ironic foreshadowing |
| 按下不表 | Set aside for now | Borrowed from 评书 (traditional storytelling) |

### Tone & Voice Characteristics

- **Delivery:** Deadpan, fast-paced, highly sarcastic
- **"废话文学" (nonsense literature):** Redundant/circular phrasing for comedy — e.g., "这个长得像小女孩的小女孩，其实是一个小女孩"
- **Pseudo-idioms:** Invents fake classical phrases like "饮恨西北"
- **Philosophy:** Maximize information density, minimize cognitive load
- **Perspective:** Third-person omniscient, detached narrator

### TTS Voice for Uncle Niu Style

- Generic channels use Microsoft Azure "云希" voice (cheerful style) or Alibaba Cloud AI
- User wants to clone Uncle Niu's actual voice using Fish Speech
- **Needs:** 10-30 second clean audio clip of Uncle Niu speaking (no background music)

---

## Key Design Insight

The PRD targets **~10 minutes**, but the generic "注意看/小帅小美" style is designed for **3-minute Douyin/TikTok** clips. Uncle Niu's YouTube channel does longer-form reviews. The style file must account for **pacing differences**:

- 3-min format: pure rapid-fire compression, no structure
- 10-min format: needs act structure (setup → escalation → climax → resolution), breathing room, deeper sarcasm

This is the key differentiator that transcript analysis will reveal — how Uncle Niu paces a 10-minute narrative vs the generic formula.

---

## Completed This Session (2026-03-31)

1. **YouTube subtitles:** Confirmed none of the 7 videos have subtitles (not even auto-generated). YouTube auto-captions don't reliably work for Chinese narration channels.

2. **Audio downloaded:** All 7 videos' audio extracted as MP3 to `transcripts/` folder (54MB total):
   - `01_rebel_girl.mp3` through `07_retired_soldier.mp3`
   - Ready for Whisper transcription when installed

3. **Voice cloning samples:** 5 x 30-second clips cut from video 7 at different timestamps:
   - `voice-samples/sample_15s.mp3`, `sample_120s.mp3`, `sample_300s.mp3`, `sample_450s.mp3`, `sample_600s.mp3`
   - User needs to listen and pick the cleanest one (no background music, clear speech)
   - Full audio also saved: `voice-samples/uncle_niu_full.mp3`

4. **Style file written:** `styles/niu-shu.md` — 10 sections covering:
   - Opening hook formula (注意看)
   - Full character archetype table (11 primary + 8 secondary)
   - Four-act narrative structure for 10-min format
   - Tone rules (deadpan, 废话文学, pseudo-idioms, sarcastic commentary)
   - Transition phrases
   - Plot compression rules
   - Closing patterns
   - Hard constraints
   - Script output format
   - Archetype assignment workflow

---

## Completed This Session (2026-04-01)

1. **Style C candidate identified:** YouTube channel "小岛电影" (@Vithun51) — emotional/sentimental movie review style, distinct from both Uncle Niu (sarcastic) and first-person POV (immersive).

2. **Target video analyzed:** "8.9高分经典电影！善良的好人被误解，是人间最痛心的事！" (14:02, about The Green Mile). No subtitles available.

3. **Audio downloaded:** `transcripts/xiaodao_greenline.mp3` (13.4MB) — ready for Whisper transcription.

4. **Channel catalog analyzed:** 40 video titles scraped via yt-dlp. Two content formats identified:
   - Long-form reviews (10-34 min) tagged #我的观影报告 — the core style to emulate
   - Short promos (2-7 min) for new releases — not the target style

5. **Style analysis documented:** Key differentiators vs Style A and B mapped out across 8 dimensions (perspective, tone, pacing, characters, commentary, hook style, film selection, closing). Full research at `docs/style-c-xiaodao-research.md`.

6. **Key finding:** Xiaodao style uses second-person emotional address ("你"), sincere/warm tone (no sarcasm), measured pacing, real character names (not archetypes), and philosophical reflective closings. Target audience: people seeking meaning and catharsis, not entertainment.

---

## Open Questions (To Resolve Next Session)

1. **Whisper transcription:** Install `faster-whisper` (GPU-accelerated) and transcribe all 7 audio files to Chinese text. Use results to refine the style file with real pacing data and additional transition phrases.
   ```bash
   pip install faster-whisper
   ```

2. **Voice cloning sample selection:** User must listen to the 5 sample clips and pick the cleanest one for Fish Speech reference audio.

3. **Style B (First-Person POV):** Not yet discussed. Needs its own brainstorming round — protagonist selection logic, emotional tone calibration, knowledge-boundary rules.

4. **Style A file refinement:** Once Whisper transcripts are available, compare the style file's act structure and pacing assumptions against Uncle Niu's actual narration patterns. Adjust character counts, transition frequency, and commentary density based on real data.

5. **Style C (Xiaodao) transcript + style file:** Transcribe `transcripts/xiaodao_greenline.mp3`, then write `styles/xiaodao.md`. Consider downloading 1-2 more long-form Xiaodao videos for pattern confirmation. Research doc at `docs/style-c-xiaodao-research.md`.

---

## Sources

- [知乎: "注意看，这个男人叫小帅"](https://zhuanlan.zhihu.com/p/581510859)
- [虎嗅: 注意看，"小帅和小美"正在肢解电影](https://m.huxiu.com/article/713933.html)
- [品玩: 标题党、废话文学和AI配音的烂梗](https://www.pingwest.com/a/268501)
- [知乎: 解说文案思路套路模板](https://zhuanlan.zhihu.com/p/614799957)
- [爱范儿: 小帅和小美用三分钟毁掉电影](https://www.ifanr.com/1524332)
