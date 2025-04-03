
let version = 'v4';
let path = `/assets/html/${version}.html`;

function switch_versions(event) {
  let menu = event.target;
  version = menu.options[menu.selectedIndex].value;
};

fetch(path)
    .then(response => response.text())
    .then(data => {document.getElementById('header').innerHTML = data;})
    .catch(error => console.error('Error loading HTML:', error));

export { switch_versions };