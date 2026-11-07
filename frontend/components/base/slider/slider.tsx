"use client";

import {
  Slider as AriaSlider,
  SliderThumb as AriaSliderThumb,
  SliderTrack as AriaSliderTrack,
  type SliderProps as AriaSliderProps,
} from "react-aria-components";
import { cx } from "@/utils/cx";

export interface SliderProps extends Omit<AriaSliderProps<number>, "children" | "className"> {
  /** Accessible name. Required because the slider has no visible label of its own. */
  "aria-label": string;
  className?: string;
}

/** A single-thumb slider on react-aria, with keyboard, touch and RTL support. */
export function Slider({ className, ...props }: SliderProps) {
  return (
    <AriaSlider {...props} className={cx("flex w-full items-center", className)}>
      <AriaSliderTrack className="relative h-6 w-full cursor-pointer data-[disabled]:cursor-not-allowed">
        {({ state }) => (
          <>
            <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-border-button-default" />
            <div
              className="absolute start-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-accent-500"
              style={{ width: `${state.getThumbPercent(0) * 100}%` }}
            />
            <AriaSliderThumb className="top-1/2 size-5 rounded-full border-2 border-background-primary-default bg-accent-500 shadow-sm outline-none data-[dragging]:bg-accent-600 data-[focus-visible]:ring-2 data-[focus-visible]:ring-accent-500" />
          </>
        )}
      </AriaSliderTrack>
    </AriaSlider>
  );
}
