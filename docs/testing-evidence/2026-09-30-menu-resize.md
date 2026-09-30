# Menu card height

Change-kind: feature

Medium native pointer-event test owns its window and sends a fixed sequence:
screen Y 310 down; 230, 210, 330 dragged, moving the window between events.
The product oracle is heights 580, 600, 480 from an initial 500. Before wiring
mouseDragged this assertion failed with an empty sequence. It passed after the
screen-coordinate implementation. A separate private-defaults test checks
persistence and the current screen's upper and lower bounds.

Falsification, all observed assertion failures:

- Remove persistence: reloaded height 500 instead of 650.
- Remove upper bound: 900 instead of 700; 600 instead of 300 on a small screen.
- Remove lower bound: 10 instead of 360.
- Accumulate each delta against current height: 580,680,660 instead of 580,600,480.

Focused green: two tests, 0.073 seconds. Full local Swift suite is run under the
60-second process deadline. Hardware multi-display pointer acceptance remains
manual; these tests control window geometry rather than relying on a display.
Remove when the resizable card is retired.
