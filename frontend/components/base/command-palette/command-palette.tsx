"use client";

import { useEffect, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import {
  Autocomplete as AriaAutocomplete,
  Dialog as AriaDialog,
  Header as AriaHeader,
  Input as AriaInput,
  Menu as AriaMenu,
  MenuItem as AriaMenuItem,
  MenuSection as AriaMenuSection,
  Modal as AriaModal,
  ModalOverlay as AriaModalOverlay,
  SearchField as AriaSearchField,
  useFilter,
} from "react-aria-components";
import type { Key, MenuItemProps as AriaMenuItemProps } from "react-aria-components";
import { RiCornerDownLeftLine, RiSearchLine } from "@remixicon/react";
import { Kbd } from "@/components/base/kbd/kbd";
import { useDirection } from "@/components/foundations/direction/direction";
import { ScrollFade, useScrollFade } from "@/components/foundations/scroll-fade/scroll-fade";
import { useTemplateCopy } from "@/components/foundations/template-copy/template-copy";
import { cx } from "@/utils/cx";

/**
 * Command palette — a searchable list of actions and destinations, opened
 * with ⌘K / Ctrl+K: jump to a page, run a command, find a record.
 *
 *   <CommandPalette isOpen={open} onOpenChange={setOpen}>
 *     <CommandPaletteSection title="Navigation">
 *       <CommandPaletteItem id="home" icon={RiHome5Line} onAction={…}>Dashboard</CommandPaletteItem>
 *     </CommandPaletteSection>
 *   </CommandPalette>
 *
 * Promoted from the docs site's component search, with its surface and
 * motion: a black/20 scrim, a radius/3xl panel 12vh from the top that fades
 * in, lifts 10px and sharpens from a 4px blur over 200ms, a search row over
 * a scrolling list (with the shared progressive top blur), and a footer of
 * keyboard hints.
 *
 * Built on React Aria's Autocomplete and Menu in a modal dialog, so the
 * input keeps focus while arrows move a virtual highlight through the list,
 * Enter runs the highlighted command, Escape clears the query and then
 * closes, and focus returns to wherever it was. Items filter by their text
 * with a locale-aware contains match; pass `filter={null}` and filter the
 * children yourself for custom ranking. The palette's own copy (label,
 * placeholder, empty state, hints) goes through `useTemplateCopy`, so a
 * TemplateCopyProvider translates it.
 */

type IconComponent = ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;

export interface CommandPaletteProps {
  isOpen?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (isOpen: boolean) => void;
  /** Letter that opens and closes it with ⌘ / Ctrl. `false` turns the shortcut off. Default "k". */
  shortcut?: string | false;
  /** Accessible name of the dialog. Default "Command palette". */
  "aria-label"?: string;
  placeholder?: string;
  /** Controlled query. */
  inputValue?: string;
  onInputChange?: (value: string) => void;
  /** Match items against the query; `null` shows the children as given. Default: contains, ignoring case and accents. */
  filter?: ((textValue: string, inputValue: string) => boolean) | null;
  /** Called with the id of the item run from the keyboard or the pointer, after the palette closes. */
  onAction?: (key: Key) => void;
  /** Shown when nothing matches. */
  emptyState?: ReactNode;
  /** The hint row under the list; `false` hides it. */
  footer?: ReactNode | false;
  className?: string;
  children: ReactNode;
}

export function CommandPalette({
  isOpen: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  shortcut = "k",
  "aria-label": ariaLabel = "Command palette",
  placeholder = "Type a command or search…",
  inputValue: controlledInput,
  onInputChange,
  filter,
  onAction,
  emptyState = "No results",
  footer,
  className,
  children,
}: CommandPaletteProps) {
  const direction = useDirection();
  const localize = useTemplateCopy();
  const label = localize(ariaLabel);
  const { contains } = useFilter({ sensitivity: "base" });
  const fade = useScrollFade();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const [uncontrolledInput, setUncontrolledInput] = useState("");
  const isOpen = controlledOpen ?? uncontrolledOpen;
  const inputValue = controlledInput ?? uncontrolledInput;

  const setOpen = (next: boolean) => {
    setUncontrolledOpen(next);
    onOpenChange?.(next);
    if (next) {
      // Every opening starts fresh: an empty query and the list at its top.
      setUncontrolledInput("");
      onInputChange?.("");
      fade.reset();
    }
  };

  useEffect(() => {
    if (shortcut === false) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== shortcut.toLowerCase()) return;
      event.preventDefault();
      setOpen(!isOpen);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  return (
    <AriaModalOverlay
      isOpen={isOpen}
      onOpenChange={setOpen}
      isDismissable
      dir={direction}
      className="group/palette fixed inset-x-0 top-0 z-100 flex h-(--visual-viewport-height) items-start justify-center px-4 pt-[12vh]"
    >
      <div
        aria-hidden
        className="absolute inset-0 bg-black/20 transition-opacity duration-150 ease-out group-data-[entering]/palette:opacity-0 group-data-[exiting]/palette:opacity-0"
      />
      <AriaModal
        className={cx(
          "relative flex max-h-[min(560px,76vh)] w-full max-w-[560px] flex-col outline-none",
          "transition-[opacity,translate,scale,filter] duration-200 ease-out",
          "data-[entering]:opacity-0 data-[exiting]:opacity-0",
          "motion-safe:data-[entering]:translate-y-2.5 motion-safe:data-[entering]:scale-[0.98] motion-safe:data-[entering]:blur-[4px]",
          "motion-safe:data-[exiting]:translate-y-2 motion-safe:data-[exiting]:scale-[0.98] motion-safe:data-[exiting]:blur-[3px]",
        )}
      >
        <AriaDialog
          aria-label={label}
          className={cx(
            "flex min-h-0 flex-1 flex-col overflow-clip rounded-3xl border border-border-button-default bg-background-primary-default shadow-sidebar outline-none",
            className,
          )}
        >
          <AriaAutocomplete
            inputValue={inputValue}
            onInputChange={(value) => {
              setUncontrolledInput(value);
              onInputChange?.(value);
            }}
            filter={filter === null ? undefined : filter ?? contains}
          >
            <AriaSearchField aria-label={label} autoFocus className="flex shrink-0 items-center gap-2 border-b border-separator-border p-3">
              <RiSearchLine className="size-5 shrink-0 text-foreground-icon-secondary" aria-hidden />
              <AriaInput
                placeholder={localize(placeholder)}
                className="min-w-0 flex-1 bg-transparent text-body-medium text-text-primary outline-none placeholder:text-text-tertiary [&::-webkit-search-cancel-button]:hidden"
              />
            </AriaSearchField>
            <div className="relative flex min-h-0 flex-1 flex-col">
              <AriaMenu
                aria-label={label}
                onScroll={fade.onScroll}
                onAction={(key) => {
                  setOpen(false);
                  onAction?.(key);
                }}
                renderEmptyState={() => (
                  <div className="flex min-h-32 flex-col items-center justify-center gap-1 px-4 text-center text-body-medium text-text-tertiary">
                    {localize(emptyState)}
                  </div>
                )}
                className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto overscroll-contain p-2 outline-none [scrollbar-width:thin]"
              >
                {children}
              </AriaMenu>
              <ScrollFade progress={fade.progress} />
            </div>
          </AriaAutocomplete>
          {footer === false ? null : (
            <div className="flex shrink-0 items-center justify-between border-t border-separator-border px-3 py-2 text-body-regular text-text-tertiary">
              {localize(
                footer ?? (
                  <>
                    <span>Navigate with ↑ ↓</span>
                    <span className="flex items-center gap-1.5">
                      Select
                      <Kbd aria-label="Enter">
                        <RiCornerDownLeftLine className="size-3" aria-hidden />
                      </Kbd>
                    </span>
                  </>
                ),
              )}
            </div>
          )}
        </AriaDialog>
      </AriaModal>
    </AriaModalOverlay>
  );
}

export interface CommandPaletteItemProps extends Omit<AriaMenuItemProps, "children" | "className"> {
  /** Remix Icon before the label. */
  icon?: IconComponent;
  /** Muted text at the end of the row, e.g. the section or a path. */
  description?: ReactNode;
  /** Keyboard shortcut shown at the end of the row, e.g. "⌘N". */
  shortcut?: string;
  className?: string;
  children: ReactNode;
}

export function CommandPaletteItem({ icon: Icon, description, shortcut, className, children, ...props }: CommandPaletteItemProps) {
  return (
    <AriaMenuItem
      {...props}
      textValue={props.textValue ?? (typeof children === "string" ? children : undefined)}
      className={({ isFocused }) =>
        cx(
          "flex w-full cursor-pointer items-center gap-2 rounded-xl px-3 py-2.5 text-start outline-none transition-colors duration-100 ease-out",
          isFocused && "bg-background-secondary-default",
          "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
          className,
        )
      }
    >
      <span className="flex min-w-0 flex-1 items-center gap-2">
        {Icon ? <Icon className="size-4 shrink-0 text-foreground-icon-secondary" aria-hidden /> : null}
        <span className="flex min-w-0 items-center gap-2 truncate text-body-medium text-text-primary">{children}</span>
      </span>
      {description ? <span className="shrink-0 text-body-regular text-text-tertiary">{description}</span> : null}
      {shortcut ? <Kbd>{shortcut}</Kbd> : null}
    </AriaMenuItem>
  );
}

export interface CommandPaletteSectionProps {
  /** Muted heading above the section's items. */
  title?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function CommandPaletteSection({ title, className, children }: CommandPaletteSectionProps) {
  return (
    <AriaMenuSection className={cx("flex flex-col gap-0.5 [&:not(:first-child)]:pt-2", className)}>
      {title ? <AriaHeader className="px-3 pt-1 pb-1 text-body-2-medium text-text-tertiary">{title}</AriaHeader> : null}
      {children}
    </AriaMenuSection>
  );
}
