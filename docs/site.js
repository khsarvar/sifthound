// Shared script for the Sifthound project site: adds a "Copy" button to every code block.
// Pages work without it; the buttons are an enhancement.
document.querySelectorAll("pre").forEach((pre) => {
  const wrapper = document.createElement("div");
  wrapper.className = "code-block";
  pre.replaceWith(wrapper);
  wrapper.append(pre);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button";
  button.textContent = "Copy";
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
    button.textContent = "Copied";
    button.classList.add("copied");
    setTimeout(() => {
      button.textContent = "Copy";
      button.classList.remove("copied");
    }, 1500);
  });
});
