# Example requirements

Small rule profiles to copy and adapt. Each one is a starting point: change the
prop kinds, names or parts of the song to fit your display.

| File | What it does |
| --- | --- |
| `keep-the-star-on.yaml` | Every star stays lit all song |
| `gentle-show.yaml` | Dimmer mega tree and arches; the tree rests in the intro and outro |
| `save-the-tree-for-the-chorus.yaml` | The mega tree only lights in the loud parts |
| `skip-a-broken-prop.yaml` | Leaves one named prop out of every show |

Use one or more with `generate`:

```powershell
uv run lor-sequence-builder generate --preview display.lorprev --audio song.mp3 --output song.loredit --rules examples\requirements\gentle-show.yaml
```

Props can be chosen by kind (`role: arch`, `mini_tree`, `mega_tree`, `snowflake`,
`star`, `outline`, `icicles`, `decor`), by an S6 group (`group: Arches`) or by name
(`names: [Arch 3]`). Parts of the song are `intro`, `verse`, `pre-chorus`,
`chorus`, `bridge`, `instrumental`, `breakdown`, `solo`, `outro` and `finale`.
The full list of requirement types is in [docs/RULES.md](../../docs/RULES.md).
In the browser workspace, the New show panel builds the same requirements from a form.
