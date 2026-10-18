import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdcard"))
import prepare_sdcard  # noqa: E402

IMAGER_FIRSTRUN = """#!/bin/bash
set +e
CURRENT_HOSTNAME=`cat /etc/hostname | tr -d " \\t\\n\\r"`
echo falcon-node >/etc/hostname
rm -f /boot/firstrun.sh
sed -i 's| systemd.run.*||g' /boot/cmdline.txt
exit 0
"""


def boot(tmp_path: Path, extra: dict[str, str]) -> Path:
    for name, text in {"config.txt": "arm_64bit=1\n", "cmdline.txt": "console=tty1 root=PARTUUID=x\n", **extra}.items():
        (tmp_path / name).write_text(text)
    return tmp_path


def test_refuses_a_folder_that_is_not_a_boot_partition(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="bootfs"):
        prepare_sdcard.main([str(tmp_path)])


def test_imager_first_boot_script_schedules_the_install_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    card = boot(tmp_path, {"firstrun.sh": IMAGER_FIRSTRUN})
    prepare_sdcard.main([str(card), "--name", "Pond node", "--rain", "off"])
    prepare_sdcard.main([str(card), "--name", "Pond node"])  # running twice changes nothing important
    script = (card / "firstrun.sh").read_text()
    assert script.count("firstboot-hook.sh") == 2  # one line, mentioned twice (test and call)
    assert script.index("firstboot-hook.sh") < script.index("rm -f /boot/firstrun.sh")
    bundle = card / "falcon-node"
    for path in ("install.sh", "falcon_node/agent.py", "systemd/falcon-node.service",
                 "sdcard/firstboot-hook.sh", "audio/da7212-onboard-mic1.state", "node.conf", "PAIRING.txt"):
        assert (bundle / path).is_file(), path
    assert not list(bundle.rglob("__pycache__"))
    config = (bundle / "node.conf").read_text()
    assert "NODE_NAME=Pond node" in config and "RAIN=off" in config
    keys = [line for line in config.splitlines() if line.startswith("PAIRING_KEY=")]
    assert len(keys) == 1 and len(keys[0]) == len("PAIRING_KEY=") + 29
    output = capsys.readouterr().out
    assert output.count(keys[0].split("=")[1]) == 2 and "First boot is set up" in output


def test_cloud_init_runcmd_is_added_or_extended(tmp_path: Path) -> None:
    card = boot(tmp_path, {"user-data": "#cloud-config\nhostname: falcon-node\nruncmd:\n- [touch, /tmp/x]\n"})
    prepare_sdcard.main([str(card)])
    prepare_sdcard.main([str(card)])
    text = (card / "user-data").read_text()
    assert text.count("firstboot-hook.sh") == 1
    assert "runcmd:\n- [bash, /boot/firmware/falcon-node/sdcard/firstboot-hook.sh, --now]\n- [touch, /tmp/x]" in text
    (tmp_path / "fresh").mkdir()
    fresh = boot(tmp_path / "fresh", {"user-data": "#cloud-config\nhostname: n\n"})
    prepare_sdcard.main([str(fresh)])
    assert (fresh / "user-data").read_text().endswith(
        "runcmd:\n  - [bash, /boot/firmware/falcon-node/sdcard/firstboot-hook.sh, --now]\n"
    )


def test_plain_card_gets_the_one_command_instruction(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prepare_sdcard.main([str(boot(tmp_path, {}))])
    assert "sudo bash /boot/firmware/falcon-node/install.sh" in capsys.readouterr().out
