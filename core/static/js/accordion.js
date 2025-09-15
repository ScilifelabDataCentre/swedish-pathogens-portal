/**
 * Accordion functionality for interactive collapsible content
 * Used on the Pathogens Portal Nodes page
 */

document.addEventListener('DOMContentLoaded', function() {
  function toggleAccordion(accordionId) {
    const content = document.getElementById(accordionId + '-content');
    const icon = document.getElementById(accordionId + '-icon');
    const button = icon.closest('button');
    
    if (!content || !icon || !button) {
      console.error('Accordion elements not found for:', accordionId);
      return;
    }
    
    if (content.classList.contains('hidden')) {
      // Expand accordion
      content.classList.remove('hidden');
      icon.style.transform = 'rotate(180deg)';
      button.setAttribute('aria-expanded', 'true');
    } else {
      // Collapse accordion
      content.classList.add('hidden');
      icon.style.transform = 'rotate(0deg)';
      button.setAttribute('aria-expanded', 'false');
    }
  }
  
  // Make the function globally available
  window.toggleAccordion = toggleAccordion;
});
