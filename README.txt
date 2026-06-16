EMS FTMS v16.17 final ERG reverse KP anti-overshoot

Base: v16.16

Changes in this version:
- ERG mode uses Target Watt + RPM to reverse lookup required KP from the Watt table.
- RPM rapid-rise anti-overshoot lowers KP proactively.
- KP decreases quickly and recovers slowly for smoother pedal feel.
- Does not use FTMS Power as feedback.
- RPM, Watt display table, idle watt table, and Stop logic are kept from v16.16.
