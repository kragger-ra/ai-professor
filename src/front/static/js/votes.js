let previousVoteData = null;
let proxyData = {};
let dataBackup = null;
let updateVotesLock = false;
let UPDATE_INTERVAL = 500;

function createVoteBlocks(count) {
    let blocks = '';
    for (let i = 0; i < count; i++) {
        blocks += '<div class="vote-unit"></div>';
    }
    return blocks;
}

function createVoteBlock(result, isWinner = false) {
    return `<div class="vote-block${isWinner ? ' winner' : ''}">
        <span class="vote-label">${result.type}: ${result.count}</span>
        <div class="vote-bar">
            ${createVoteBlocks(result.count)}
        </div>
        ${isWinner ? '<span class="vote-winner-text">Победитель!</span>' : '<span class="vote-winner-text"></span>'}
    </div>`;
}

function updateVoteBlock(element, result, isWinner = false) {
    const label = element.querySelector('.vote-label');
    const bar = element.querySelector('.vote-bar');
    
    label.textContent = `${result.type}: ${result.count}`;
    bar.innerHTML = createVoteBlocks(result.count);
    
    if (isWinner) {
        element.classList.add('winner');
        if (!element.querySelector('.vote-winner-text')) {
            const winnerText = document.createElement('span');
            winnerText.className = 'vote-winner-text';
            winnerText.textContent = 'Победитель!';
            element.appendChild(winnerText);
        }
    } else {
        element.classList.remove('winner');
        const winnerText = element.querySelector('.vote-winner-text');
        if (winnerText) winnerText.remove();
    }
}

function hasVoteDataChanged(oldData, newData) {
    if (!oldData && newData) return true;
    if (!newData && oldData) return true;
    if (!oldData && !newData) return false;
    if (oldData.topic !== newData.topic) return true;
    
    const oldVotes = JSON.stringify(oldData.results);
    const newVotes = JSON.stringify(newData.results);
    return oldVotes !== newVotes;
}

function hasTopicChanged(oldData, newData) {
    if (!oldData || !newData) return false;
    if (!oldData.has_votes || !newData.has_votes) return false;
    if (oldData.topic !== newData.topic) return true;
    return false;
}

function updateVotesInner(data){
    const container = document.getElementById('vote-container');
    const topicChanged = !updateVotesLock && hasTopicChanged(previousVoteData, data);
    
    const emptyData = {"has_votes": false, "topic": "", "results": []};
    if(topicChanged && !updateVotesLock){
        console.log('topic changed');
        proxyData = emptyData;
        updateVotesLock = true;
        setTimeout(() => { updateVotesLock = false; previousVoteData = emptyData; }, UPDATE_INTERVAL+2000);
    }
    if (updateVotesLock){
        data = proxyData;
    } else {
        proxyData = data;
    }
    const dataChanged = hasVoteDataChanged(previousVoteData, data);
    if (data.has_votes) {
        if (dataChanged) {
            if (!container.querySelector('.vote-container')) {
                container.innerHTML = `<div class="vote-container">
                    <div class="vote-topic">
                        <p>«${data.topic}»</p>
                        ${data.winner ? '' : '<div class="vote-header">Голосуйте!</div>'}
                    </div>
                </div>`;
            }
            const voteContainer = container.querySelector('.vote-container');
            const newBlocks = data.results.map(result => {
                const isWinner = data.winner && data.winner.winner === result.type;
                return createVoteBlock(result, isWinner);
            });
            const newBlocksHtml = newBlocks.join('');
            
            let existingBlocks = voteContainer.querySelectorAll('.vote-block');

            if (existingBlocks.length == 0 || existingBlocks.length != newBlocks.length){
                voteContainer.insertAdjacentHTML('beforeend', newBlocksHtml);
            }
            data.results.forEach((result, index) => {
                if (existingBlocks[index]) {
                    const label = existingBlocks[index].querySelector('.vote-label');
                    const newTextContent = `${result.type}: ${result.count}`
                    if (newTextContent !== label.textContent){
                        label.textContent = newTextContent;
                    }
                    //existingBlocks[index].style.animationDelay = `${(index + 1) * 100}ms`;
                    const isWinner = data.winner && data.winner.winner === result.type;
                    if (isWinner && !existingBlocks[index].classList.contains('winner')) {
                        existingBlocks[index].classList.add('slide-left-exit');
                        existingBlocks[index].addEventListener('animationend', () => {
                            existingBlocks[index].classList.remove('slide-left-exit');
                            const winnerText = existingBlocks[index].querySelector('.vote-winner-text');
                            winnerText.textContent = 'Победитель!';
                            //winnerText.style.animationDelay = `0ms`;
                            //winnerText.classList.add('slide-left-exit');

                            existingBlocks[index].classList.add('winner');

                            const headerDiv = container.querySelector('.vote-header');
            
                            if (data.winner && headerDiv) {
                                headerDiv.classList.add('vote-header-fade-out');
                                headerDiv.addEventListener('animationend', () => {
                                    //headerDiv.remove();
                                    headerDiv.classList.remove('vote-header-fade-out');
                                    headerDiv.classList.add('vote-header-finished');
                                    headerDiv.textContent = 'Голосование завершено!';
                                    //voteStatus.className = 'vote-status slide-down';
                                    //voteStatus.textContent = 'Голосование завершено!';
                                });
                            }
        

                        });
                    }
                    const bar = existingBlocks[index].querySelector('.vote-bar');
                    const currentUnits = bar.children.length;
                    const targetUnits = result.count;
                    
                    if (currentUnits !== targetUnits) {
                        //bar.classList.add('fade-out-exit');
                        //setTimeout(() => {
                            //bar.classList.remove('fade-out-exit');
                            for (let i = 0; i < Math.abs(targetUnits - currentUnits); i++) {
                                newBlock = document.createElement("div")
                                newBlock.className = "vote-unit"
                                bar.appendChild(newBlock)
                            }

                        //}, (index + 7) * 100);
                        
                    }
                }
            });
        } else if (previousVoteData) {
            //const voteStatus = container.querySelector('.vote-status');

            const voteBlocks = container.querySelectorAll('.vote-block');
            data.results.forEach((result, index) => {
                if (voteBlocks[index]) {
                    const label = voteBlocks[index].querySelector('.vote-label');
                    label.textContent = `${result.type}: ${result.count}`;
                    
                    const bar = voteBlocks[index].querySelector('.vote-bar');
                    const currentUnits = bar.children.length;
                    const targetUnits = result.count;
                    
                    if (currentUnits !== targetUnits) {
                        bar.innerHTML = createVoteBlocks(targetUnits);
                    }
                }
            });
        }
    } else if (dataChanged) {
        const existingContent = container.querySelector('.vote-container');
        if (existingContent) {
            const blocks = existingContent.querySelectorAll('.vote-block');
            blocks.forEach((block, index) => {
                block.classList.add('slide-left-exit');
                block.style.animationDelay = `${index * 0.1}s`;
            });
            
            const topic = existingContent.querySelector('.vote-topic');
            if (topic) {
                topic.classList.add('slide-up-exit');
                topic.style.animationDelay = `${blocks.length * 0.1}s`;
            }
            
            existingContent.classList.add('fade-out-exit');
            existingContent.style.animationDelay = `${(blocks.length + 1) * 0.1}s`;
            
            setTimeout(() => {
                existingContent.remove();
            }, (blocks.length + 1) * 500);
        } else {
            container.innerHTML = '<p></p>';
        }
    }

    if (!topicChanged) {
        previousVoteData = data.has_votes ? {...data} : emptyData;
    }
    
    console.log(previousVoteData);
}


function updateVotes() {
    fetch('/hud_data')
        .then(response => response.json())
        .then(data => {
            updateVotesInner(data);
        })
        .catch(error => console.error('Error:', error));
}

setInterval(updateVotes, UPDATE_INTERVAL);