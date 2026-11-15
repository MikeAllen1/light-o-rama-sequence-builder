# The 10-second display test

Before a full show, check your wiring. In New show, after choosing your display, click **10-second display test**:

| Time | What lights |
| --- | --- |
| 0.5 to 6.5 s | One kind of prop at a time. A prop with several channels lights them one after another, so a strand wired backwards shows. RGB props show red, green, blue, then white. A singing face steps through its mouths. |
| 6.5 to 9.0 s | A sweep across the yard, left to right. |
| 9.0 to 10.0 s | Everything on, then a fade. |

**Watch the test** plays it on the yard view. **Save test files** downloads a zip with the sequence, its sound (`LOR Display Test.wav`, which goes in S6's audio folder) and a "what to watch" list.

Anything dark or out of order points at wiring, a controller address or the preview. Two props wired to the same circuit (a roofline on a mega tree's last channel) show as one light.

S5/S6 displays only. Command line: `lor-sequence-builder display-test --preview display.lorprev --output "Display Test"`.
