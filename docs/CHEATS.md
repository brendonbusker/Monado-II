# Optional Linux cheats (0.1.15)

Open the launcher's **Cheats** tab. Each option has its own checkbox and starts
disabled. Enable the options you want, select **Save settings**, then start the
game. Changes apply on the next game launch.

| Option | Effect |
|---|---|
| Party damage dealt | Scale positive battle-hit damage from party characters to enemies. |
| Party damage received | Scale positive battle-hit damage from enemies to party characters. |
| EXP gained | Scale new EXP awards, including the native bonus-EXP award mode. |
| AP gained | Scale new AP awards. |
| SP gained | Scale new SP awards. |
| Gold gained | Scale new positive gold awards; purchases and spending stay native. |
| No fall damage | Prevent ordinary party-character landing damage, including otherwise lethal ordinary drops. |

Each multiplier spans **0.00x to 20.00x**, in **0.01x** steps. The slider stores
percentages: **100% = 1.00x**, **200% = 2.00x**, and **2000% = 20.00x**. Zero
means no damage or gain for that option. With an active slider, **Ctrl+arrow**
adjusts one percentage point; **Ctrl+click** allows an exact percentage to be
typed. Native game caps still apply and fractional units round down. The chosen
slider value is retained while its checkbox is off.

The party options use the native source/target classification, including party
AI, rather than only the controlled character. The native immunity, revival and
death systems remain in place. Healing and ally-to-ally/enemy-to-enemy events
retain their original behavior. Damage-over-time and separate status-effect
paths are not yet comprehensively qualified; don't assume every effect is scaled.

No fall damage uses the native no-damage landing return path. Normal landing
animation and movement resets remain. The native forced-collision path and
separate environmental/scripted damage systems are retained; this option is not
general immunity or a promise of survival outside the playable world.

EXP/AP/SP awards preserve the game's party/story eligibility, skill handling,
level-ups and caps. Expert Mode's transfer of EXP already earned is not multiplied
again. Native award notifications receive the scaled values; static quest-reward
previews can still show their base values.

## Saves and testing

These preferences do not change the native save format. **Levels, EXP, AP, SP
and gold already earned remain in your save after disabling cheats.** Test new
settings on a spare save and retain normal backups. A capped level or balance
can make a multiplier appear to have no effect.

Authored native configuration/arithmetic/adaptor fixtures, strict patch guards
and controlled selected-input instruction probes exercise the integration. They
are component evidence. The maintainer manually accepted the combined Linux
build. Both DE and Future Connected use the shared native routes, but this
does not establish complete coverage of every reward, effect, scripted encounter
or fall. Faster Arts recharge is excluded. Windows implementation is unchanged.
