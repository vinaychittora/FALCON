# Audio HAT mixer settings

`da7212-onboard-mic1.state` is Waveshare's ALSA mixer snapshot for the DA7212 Audio HAT (B)
that switches on onboard microphone 1 and switches off the other inputs and outputs. The
HAT is compatible with the Raspberry Pi Codec Zero, so the card is named `Zero`.

falcon-node restores it with `alsactl --file da7212-onboard-mic1.state restore Zero` each
time the stream starts, so the microphone works after every boot.

Source: https://github.com/waveshareteam/DA7212-Audio-HAT-B (examples/DA7212-Audio-HAT-B-Config.zip,
file `OnBoard-MIC1-input.state`), Apache License 2.0, copyright Waveshare. See
`LICENSE-waveshare.txt`. The file is unchanged.
