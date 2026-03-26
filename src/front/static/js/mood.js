function updateMood() {
    fetch('/mood_data')
        .then(response => response.json())
        .then(data => {
            document.getElementById('mood-container').innerHTML = 
                `<p>${data.emoji} ${data.mood}</p>`;
            document.documentElement.style.setProperty('--glow-color', data.color);
        });
}

setInterval(updateMood, 100);
