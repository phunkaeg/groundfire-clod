# Channel three-site trial

The prepared offline mission **GroundFire Channel Three-Site Trial** puts three AI Ju 88 bombing runs near Hawkinge, Tangmere and Calais in the same sortie. Hawkinge's aim is 60 m west of a tile boundary in the extracted fuel database. The other runs are independent controls for widely separated fires. The Channel bridge accepts supported near-ground detonations throughout the mapped footprint, using their game coordinates and the mission clock.

## Stage the mission

Use the [prepared trial kit](https://github.com/phunkaeg/groundfire-clod/releases/download/v0.2.0/channel-three-site-trial.zip), or generate it from the repository root with the extracted Channel fuel database as input.

~~~powershell
py -3 -B integrations/clod/prepare_channel_trial.py "path\to\channel-fuel.sqlite" "dist\channel-three-site-trial"
~~~

Copy the three mission files to the CloD Documents profile under **missions/Single**. Keep the bridge folder together. The script uses terrain height, effect and camera bindings from Steam vrbeta build **25283265**. It runs in single player. The fuel classification comes from the Channel overview at 128 m, and the fire model uses 10 m cells. Wind is 8 m/s toward the east in this trial.

## Run and verify

Start **bridge/Launch Channel Bridge.cmd**, then open the trial in the Single Mission list and enter flight. The initial fixed camera watches Hawkinge. Use the Mission orders menu to switch viewpoints. For capture automation, write **0**, **1** or **2** to **%LOCALAPPDATA%\GroundFireHawkinge\channel-fire\SESSION.view.txt** to choose Hawkinge, Tangmere or Calais. Replace **SESSION** with the ID in **active.txt**. Removing that temporary selector returns camera control to the mission menu.

The bridge prints accepted impact records and tile crossings. The session files in **%LOCALAPPDATA%\GroundFireHawkinge\channel-fire** include the following:

- **SESSION.flight.log** contains raw bomb callback diagnostics, camera selection and native effect creation.
- **SESSION.events.tsv** contains the accepted impact coordinates and clock samples for replay.
- **SESSION.evidence.jsonl** contains impact heat counts and tile-crossing witnesses. For a crossing, the receiving cell must newly flame with no direct bomb heat and no same-tile flaming neighbor in that step. Spotting is disabled so airborne embers do not enter the witness.

For live acceptance, check that each of the three AI groups delivers an accepted impact with a nonzero heat count. At Hawkinge, look for an eastward witness across **X = 229,376 m**, from fuel tile **(6, 2)** into **(7, 2)**. Confirm visible native effects while watching the Hawkinge view. The short trial spans several minutes of mission time.

## Recorded run

The Steam beta run accepted 18 SC 50 and two SC 250 detonations at each of the three sites. All 60 heated fuel. Hawkinge's first eastward crossing occurred at mission second 68.0, 16.58 seconds after its first impact. The recipient at **(229385, 238155)** had no direct bomb heat and no same-tile flaming neighbor at ignition. The source at **(229375, 238145)** was already flaming. Native smoke was visible from all three fixed cameras.

The replay aligns the captured frames to the wall-clock samples in the flight's event file. Its right-hand panel reconstructs the simulated fire grid from the same events and marks the crossing. Run **integrations/clod/replay_channel_trial.py --help** for replay options. [Watch the recorded trial](https://github.com/phunkaeg/groundfire-clod/releases/download/v0.2.0/channel-three-site-live.mp4)
