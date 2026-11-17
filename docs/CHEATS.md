# Optional Linux cheats

Live F1 controls, movement speed and enemy health are available in Linux 0.1.28.

Use the launcher's **Cheats** tab before playing, or press **F1** and open
**Cheats** during gameplay. Each option has its own checkbox and starts disabled.
F1 changes apply to the next relevant enemy update, hit, movement update, landing or reward,
without restarting. F1's **Save** button remembers the preferences for future
launches; unsaved changes apply to the current session only.

| Option | Effect |
|---|---|
| Party damage dealt | Scale positive battle-hit damage from party characters to enemies. |
| Party damage received | Scale positive battle-hit damage from enemies to party characters. |
| Enemy health | Scale enemies' maximum HP. Live changes preserve their remaining HP percentage, including when turning the option off. |
| EXP gained | Scale new EXP awards, including the native bonus-EXP award mode. |
| AP gained | Scale new AP awards. |
| SP gained | Scale new SP awards. |
| Gold gained | Scale new positive gold awards; purchases and spending stay native. |
| Movement speed | Multiply party locomotion after normal movement bonuses, including Quick Step. The game clock is unchanged. |
| No fall damage | Prevent ordinary party-character landing damage, including otherwise lethal ordinary drops. |

Enemy health spans **0.10x to 20.00x**. Other multipliers span **0.00x to 20.00x**,
all in **0.01x** steps. The sliders store
percentages: **100% = 1.00x**, **200% = 2.00x**, and **2000% = 20.00x**. Zero
means no damage or gain for that option, or stops movement controlled by the
movement-speed modifier. With an active slider, **Ctrl+arrow**
adjusts one percentage point; **Ctrl+click** allows an exact percentage to be
typed. Native damage/reward caps still apply and fractional award units round
down; movement uses a floating-point multiplier. The chosen
slider value is retained while its checkbox is off.

Enemy health starts disabled at 1.00x. It changes actual enemy HP, independently
of damage multipliers. Scaling starts after native HP initialization; preliminary
loading refreshes keep their native behavior. New enemies start with a matching health bar; changing
the multiplier during a fight preserves the remaining fraction instead of
refilling it. Dead enemies stay dead. Party/NPC health stays unchanged.

Native phase protections, HP floors, death handling and rewards remain active.
To preserve percentage-triggered phases and 1-HP survival protections, reduced
health has a safety minimum of 100 HP, or the original native maximum when that
is already below 100 HP. Very small health bars may therefore receive less of a
reduction than the selected multiplier. Integer HP rounding and arithmetic caps
also apply. Scripted encounters still need representative manual testing; this
does not establish complete coverage of every native or data-driven boss mechanic.

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
and gold already earned remain in your save after disabling cheats.** Enemy-health
ownership is runtime-only; its preference uses the existing settings file. Test new
settings on a spare save and retain normal backups. A capped level or balance
can make a multiplier appear to have no effect.

Authored native configuration/arithmetic/adaptor fixtures and strict patch guards
exercise the integration. They are component evidence. The earlier cheats, live
controls and movement speed were manually accepted. Prison Island loading was
manually verified with enemy health at 2x and 20x. Both DE and Future Connected
use the shared native routes, but this
does not establish complete coverage of every reward, effect, scripted encounter
or fall. Faster Arts recharge is excluded. Windows implementation is unchanged.
