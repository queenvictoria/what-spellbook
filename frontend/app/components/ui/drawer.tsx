import { Drawer as DrawerPrimitive } from '@base-ui/react/drawer'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * The shadcn Drawer, on Base UI.
 *
 * shadcn's current drawer is Base UI's `Drawer` rather than Vaul — Base UI's own guidance is
 * that Drawer extends Dialog and adds gestures and snap points on top, so a panel with no
 * swipe gesture is a positioned Dialog. This app has no use for snap points or a swipe
 * handle, but the wrapper is kept faithful to shadcn's so the parts map one-to-one and
 * `Drawer.Close` and `Drawer.Title` bring their accessibility wiring (focus trap, Escape,
 * `aria-labelledby`) rather than being re-implemented here by hand.
 *
 * The colours are this app's tokens, since shadcn's `bg-background` and `text-foreground`
 * do not exist in Tailwind v4's `@theme` here — the tokens are named in `index.css`.
 */

function Drawer({ ...props }: ComponentProps<typeof DrawerPrimitive.Root>) {
  return <DrawerPrimitive.Root data-slot="drawer" {...props} />
}

function DrawerTrigger({ ...props }: ComponentProps<typeof DrawerPrimitive.Trigger>) {
  return <DrawerPrimitive.Trigger data-slot="drawer-trigger" {...props} />
}

function DrawerPortal({ ...props }: ComponentProps<typeof DrawerPrimitive.Portal>) {
  return <DrawerPrimitive.Portal data-slot="drawer-portal" {...props} />
}

function DrawerClose({ ...props }: ComponentProps<typeof DrawerPrimitive.Close>) {
  return <DrawerPrimitive.Close data-slot="drawer-close" {...props} />
}

function DrawerBackdrop({
  className,
  ...props
}: ComponentProps<typeof DrawerPrimitive.Backdrop>) {
  return (
    <DrawerPrimitive.Backdrop
      data-slot="drawer-backdrop"
      className={cn(
        'fixed inset-0 z-50 bg-void-950/70 transition-opacity duration-200',
        'data-[starting-style]:opacity-0 data-[ending-style]:opacity-0',
        className,
      )}
      {...props}
    />
  )
}

/**
 * The popup and its children, positioned by the caller's classes.
 *
 * `swipeDirection` is what decides which edge the drawer is anchored to. `right` for this
 * app: the panel is something you read alongside the page, and sliding in from the right
 * leaves the left-hand scenario column visible.
 */
function DrawerContent({
  className,
  children,
  ...props
}: ComponentProps<typeof DrawerPrimitive.Popup>) {
  return (
    <DrawerPortal data-slot="drawer-portal">
      <DrawerBackdrop />
      {/* The viewport is what Base UI scroll-locks and anchors swipe handling to. Without
          it the popup renders but Base UI warns and swipe dismissal is disabled - so it is
          part of the anatomy rather than optional chrome. */}
      <DrawerPrimitive.Viewport
        data-slot="drawer-viewport"
        className="pointer-events-none fixed inset-0 z-50"
      >
        <DrawerPrimitive.Popup
          data-slot="drawer-content"
          className={cn(
            // `pointer-events-auto` because the viewport is a full-screen overlay that must
            // not swallow clicks meant for the page behind it; only the panel itself takes
            // them, so a click beside it reaches the backdrop and closes the drawer.
            'pointer-events-auto absolute inset-y-0 right-0 flex h-full w-full max-w-xl flex-col',
            'border-l border-void-800 bg-void-900 shadow-2xl',
            'transition-transform duration-200 ease-out',
            // `data-closed` rather than `data-[starting-style]`/`data-[ending-style]`. Base
            // UI leaves the popup mounted after the first open and drives the transition
            // off its state attribute, and the starting/ending pair stays applied once the
            // panel has been opened and closed - which parks the panel off-screen even
            // while `data-open` is set. `data-closed` is present exactly when it is shut.
            'data-[closed]:translate-x-full',
            className,
          )}
          {...props}
        >
          {children}
        </DrawerPrimitive.Popup>
      </DrawerPrimitive.Viewport>
    </DrawerPortal>
  )
}

function DrawerHeader({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="drawer-header"
      className={cn('flex flex-col gap-1 p-4', className)}
      {...props}
    />
  )
}

function DrawerFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="drawer-footer"
      className={cn('mt-auto flex flex-col gap-2 p-4', className)}
      {...props}
    />
  )
}

function DrawerTitle({ className, ...props }: ComponentProps<typeof DrawerPrimitive.Title>) {
  return (
    <DrawerPrimitive.Title
      data-slot="drawer-title"
      className={cn('font-semibold text-parchment', className)}
      {...props}
    />
  )
}

function DrawerDescription({
  className,
  ...props
}: ComponentProps<typeof DrawerPrimitive.Description>) {
  return (
    <DrawerPrimitive.Description
      data-slot="drawer-description"
      className={cn('text-sm text-parchment/50', className)}
      {...props}
    />
  )
}

export {
  Drawer,
  DrawerBackdrop,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerPortal,
  DrawerTitle,
  DrawerTrigger,
}
