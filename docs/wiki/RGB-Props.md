# RGB props

RGB floods and other RGB lights that show one color at a time (S6 calls them **DumbRGB** props: red, green and blue circuits on one prop) are part of every show, in color.

- Each part of the song takes the next color of the style's palette (see [Styles](Styles)).
- Neighbouring RGB props, left to right, alternate between two colors, so chases show both.
- Twinkles sparkle white.
- The **Only these colors** requirement limits them, for example `blue, white`.
- The yard view and the timeline show them in their real colors; the [display test](Display-Test) shows each one red, green, blue, then white.

Color names you can use: red, green, blue, white, warm white, gold, yellow, orange, purple, magenta, pink, cyan, teal, ice blue.

## Not supported yet

**Pixel props** (one channel per bulb) are listed in the display panel and the report with the reason, but not sequenced. Adding them needs an example S6 sequence with pixel props to learn the exact format from; if you have one, please open an issue.
