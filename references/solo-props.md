# Solo prop shots (offline)

Use an explicit action in the script: `假阳具自慰` → `dildo_masturbate`, `骑枕头` → `pillow_hump`, `玩具挑逗` → `toy_tease`, `仰卧假阳具自慰` → `lying_dildo`. The IDs also work directly. A bedroom, pillow or toy mentioned as scenery does not select these actions. The longer reclining action takes precedence over its shorter substring.

Preview selection without generating a project:

```sh
python scripts/whale_pose_select.py --scene 卧室 --script 仰卧假阳具自慰 --poses
```

To assemble only these actions, pass `--chain dildo_masturbate,pillow_hump,toy_tease,lying_dildo` to `scripts/whale_scene.py` with `--out-dir` and `--aspect 9:16`, `16:9`, or `1:1`. The subject occupies Picture 1; Pictures 2 and 3 both use the selected scene. Profile framing keeps the support contact in frame independently of camera movement. Run `python -X utf8 -m unittest discover -s tests -p test_solo_props.py` to exercise the offline exporter without rendering.
