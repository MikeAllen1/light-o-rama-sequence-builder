# Pixel props

If your display has pixel props (a pixel mega tree, a matrix, pixel roof lines or snowflakes, on E1.31 or LOR pixel controllers), New show offers **Light the pixel props** in step 4. It is off unless you tick it. On the command line it is `--pixels`.

## What they do

Each part of the song gets a pixel effect that suits the prop and the music:

| The music | Mega tree | Lines (roof, outline) | Snowflakes, stars | Matrix |
| --- | --- | --- | --- | --- |
| Quiet | color wash, twinkle | color wash, twinkle | color wash, twinkle | color wash, twinkle |
| Middle | garland up, spiral, blended bars | lines, blended bars, gradient | ripple, gradient, wash | blended bars, lines, ripple |
| Loud | spirals both ways, bars, meteors | meteors, bars, lines | ripple, bars, blended bars | bars, spiral, meteors, ripple |

- Quiet parts hold an idea longer; loud parts change it every couple of bars, and a loud part arrives with a short full-brightness flash.
- They use the colors the rest of the show is using in that part (or the style's colors), and go dark whenever the rest of the show is dark, so dark beats and the ending land together.
- The show eases in at the start and out at the end.
- Requirements work on pixel props too: **Never use**, **Dim**, **Only these colors**, **Keep dark during**.

## Check them in S6

This is new. The effects are written in exactly the form S6 itself saved them in a real sequence with 33 pixel props, but play the show in S6's preview and watch the pixels before show night. The Yard view in the app plays them roughly as dots; S6's visualizer is the reference.

Want different effects on a prop? Change them in the S6 Sequencer: the effects are on the prop's **Effects 01** row.
