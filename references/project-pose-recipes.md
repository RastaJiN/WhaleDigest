# Missing two-person staging action (offline scene CLI)

Create `demo/pose_recipes.json` in a fresh project directory, encoded as UTF-8:

```json
{"standing_signal":{"orientation":"Two standing subjects face each other.","support":"Both keep their weight on planted feet.","beats":["One raises a palm.","The other mirrors the gesture."],"framing":{"size":"wide","cam":"static_side"}}}
```

From the repository root:

```sh
python scripts/whale_scene.py --out-dir demo --chain standing_signal --total 5 --scene studio
python -m unittest discover -s tests -p test_local_pose.py
```

An exact standard ID wins, even if the file is malformed. Only unresolved, explicitly named chain IDs are looked up in this project. No remote lookup, shared matrix edit or inference from standing orientation. Use lowercase ASCII IDs starting with a letter (letters, digits, underscores; 64 characters maximum). Supply both subjects’ relative orientation, weight/support and 2–4 ordered visible changes. Each text field is one English phrase (up to 240 characters); framing accepts `wide` or `mcu` and `static_front` or `static_side`. Invalid requested entries stop export. Validation checks structure, not physical plausibility.

The batch shot retains the standard two-person staging primitive `pose: blocking_2s`; `custom_recipe` records the requested ID. Inspect its `blocking_state.action`, `shot_size`, `camera_motion` and `prompt` alongside 分镜.md and 视频提示词.md. Intended for silent staging in a fresh project, not automatic script selection or replacement of an adopted storyboard. Export does not pass gates or authorize rendering.
