global.__MCD = {
  startGame: startGame,
  update: update,
  rectHit: rectHit,
  getItems: function(){ return items; },
  getPlatforms: function(){ return platforms; },
  getPlayer: function(){ return player; },
  setPlayer: function(o){ Object.assign(player, o); },
  getKeys: function(){ return keys; },
  getGroundY: function(){ return groundY; }
};
