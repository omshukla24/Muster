# CALL-E feedback

I built a directory auditor on CALL-E for the hackathon and placed real calls. English worked great. Stuff I ran into, roughly worst first:

**Hindi voice is broken.** It's listed as supported for India, but on a real Hindi call the bot just looped broken syllables ("क्या…", "क्य…") for almost seven minutes and never finished a sentence. The person on the line couldn't follow it. English on the exact same setup was flawless. I have the recording.

**Got charged for calls that never connected.** A call that was rejected instantly (0 seconds, never rang through) still cost about 6 credits.

**Delivery to Indian mobiles was hit or miss.** My first call went through fine at 53 seconds. The next ones to different Indian numbers failed at 0 seconds with no reason given, so I couldn't tell if it was DND, spam blocking, or just not attempted.

**The credit model wasn't what the messaging suggested.** I planned around "20 free calls," but it's metered by duration (that 53-second call was 34 credits) and I hit low balance fast.

**No way to check balance from the CLI.** Had to open the dashboard every time, and a call just fails with "insufficient balance" instead of warning first.

**Couldn't switch accounts from the CLI.** Logging out and back in kept putting me on the same account, with no account picker.

**Hard to call the CLI from code on Windows.** It installs as calle.CMD and won't launch from a spawned process unless you route it through cmd. Fine in the terminal, breaks from a script.

**The status response is confusing.** The real data sits a few levels deep, and a run passes through states like "PREPARING" that aren't documented, so it's easy to read a call as finished when it isn't.

**Dashboard call ID isn't the CLI run ID.** Looking up a dashboard call by its ID returns "run_id not found," so I couldn't match them up.

The English calls, transcripts, and confidence scores were solid to build on. The Hindi voice is the big one.
