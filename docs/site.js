// Shared script for the Sifthound project site: adds a copy button to every code block.
// Pages work without it; the buttons are an enhancement.
const icon = (paths) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ` +
  `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const COPY_ICON = icon(
  '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
);
const CHECK_ICON = icon('<path d="M5 12.5l4.5 4.5L19 7.5"/>');

document.querySelectorAll("pre").forEach((pre) => {
  const wrapper = document.createElement("div");
  wrapper.className = "code-block";
  pre.replaceWith(wrapper);
  wrapper.append(pre);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button";
  button.innerHTML = COPY_ICON;
  button.title = "Copy";
  button.setAttribute("aria-label", "Copy code to clipboard");
  wrapper.append(button);

  button.addEventListener("click", async () => {
    const text = pre.innerText.replace(/\n$/, "");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Older browsers or non-secure pages: select the text and use the legacy copy command.
      const range = document.createRange();
      range.selectNodeContents(pre);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.execCommand("copy");
      selection.removeAllRanges();
    }
    button.innerHTML = CHECK_ICON;
    button.title = "Copied";
    button.setAttribute("aria-label", "Copied");
    button.classList.add("copied");
    setTimeout(() => {
      button.innerHTML = COPY_ICON;
      button.title = "Copy";
      button.setAttribute("aria-label", "Copy code to clipboard");
      button.classList.remove("copied");
    }, 1500);
  });
});
