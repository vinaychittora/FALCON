"""Insects and spiders at night (Vinay, 9 Nov): with this camera and infrared light
they are tiny, blurred and almost never recognised (263 visits in two hours, median box
0.07 % of the picture). Between sunset and sunrise, a visit whose classified frames
mostly name an insect or spider group (top-1 majority, or most of the top 5 in its
median frame) is kept but hidden and silent: INSECT_NIGHT, shown in Review behind
"Show unresolved" as "Insect (night, not identified)". By day nothing changes. Only
insect and spider groups count: cats, rodents, geckos, bats, owls and nightjars are
never affected. Fixed behaviour: no setting (Vinay, 9 Nov: fewer configuration knobs).
"""

from __future__ import annotations

from dataclasses import dataclass, field

INSECT_GROUPS = {"Insecta", "Lepidoptera", "Hymenoptera", "Odonata", "Arachnida"}
LABEL = "Insect (night, not identified)"


@dataclass
class InsectNight:
    frames: int = 0
    night: int = 0
    classified: int = 0
    insect: int = 0
    top5_shares: list[float] = field(default_factory=list)

    def add(self, night: bool, top_groups: list[str] | None) -> None:
        """One recorded frame: whether it is night (sun clock) and the iconic groups of
        this crop's top 5 when it was classified now."""
        self.frames += 1
        self.night += int(night)
        if top_groups:
            self.classified += 1
            self.insect += int(top_groups[0] in INSECT_GROUPS)
            five = top_groups[:5]
            self.top5_shares.append(sum(g in INSECT_GROUPS for g in five) / len(five))

    @property
    def hidden(self) -> bool:
        """Mostly at night, and an insect by top-1 majority or by the median frame's
        top 5. A night visit too small to classify counts as one."""
        if not self.frames or self.night * 2 < self.frames:
            return False
        if self.classified == 0:
            return True
        median = sorted(self.top5_shares)[len(self.top5_shares) // 2]
        return self.insect * 2 > self.classified or median > 0.5
