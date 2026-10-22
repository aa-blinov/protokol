// The kit ships as JavaScript, so it carries no declarations of its own.
// This file names what it exports; the shapes of the components come from
// the kit's own DESIGN.md.
declare module "@monos/ui" {
  export const Accordion: any;
  export const AlertDialog: any;
  export const Avatar: any;
  export const Badge: any;
  export const Breadcrumbs: any;
  export const Button: any;
  export const Card: any;
  export const Checkbox: any;
  export const Chip: any;
  export const Combobox: any;
  export const Container: any;
  export const DatePicker: any;
  export const DescriptionList: any;
  export const Drawer: any;
  export const EmptyState: any;
  export const FieldControl: any;
  export const Fieldset: any;
  export const FileUpload: any;
  export const FocusTrap: any;
  export const FormField: any;
  export const Grid: any;
  export const IconButton: any;
  export const Kbd: any;
  export const List: any;
  export const Menu: any;
  export const Modal: any;
  export const MultiSelect: any;
  export const NavItem: any;
  export const Notice: any;
  export const PageHeader: any;
  export const Pagination: any;
  export const Popover: any;
  export const Portal: any;
  export const Progress: any;
  export const Prose: any;
  export const RadioGroup: any;
  export const SearchField: any;
  export const Section: any;
  export const SegmentedControl: any;
  export const Select: any;
  export const SelectField: any;
  export const Separator: any;
  export const Sidebar: any;
  export const SidebarItem: any;
  export const SidebarSection: any;
  export const Skeleton: any;
  export const Slider: any;
  export const Spinner: any;
  export const Stack: any;
  export const Stepper: any;
  export const Switch: any;
  export const Table: any;
  export const Tabs: any;
  export const TagInput: any;
  export const TextArea: any;
  export const TextField: any;
  export const Toaster: any;
  export const Tooltip: any;
  export const fieldControlClass: any;
  /** The queue behind the Toaster: `toast()` shows a message, `toasts` is the
   *  store it keeps, `dismissToast` and `clearToasts` empty it. */
  export const toast: any;
  export const toasts: any;
  export const dismissToast: any;
  export const clearToasts: any;
}

declare module "@monos/ui/themes" {
  export const themes: Record<string, unknown>;
  export const themeNames: string[];
}
