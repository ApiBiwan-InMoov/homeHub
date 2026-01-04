<!-- app/ui/static/js/shortcuts-enhance.js -->
<script>
(function(){
  /**
   * Normalizes various boolean-ish values to true/false.
   */
  function toBool(v){
    if (v === true || v === false) return v;
    if (v == null) return false;
    if (typeof v === 'number') return v !== 0;
    const s = String(v).trim().toLowerCase();
    return (s === '1' || s === 'true' || s === 'on' || s === 'yes');
  }

  /**
   * Applies green state based on content (fallback when no data-source).
   */
  function applyFromText(button){
    const disp = button.querySelector('.js-display');
    const val = disp ? disp.textContent : '';
    button.classList.toggle('is-on', toBool(val));
  }

  /**
   * Updates all buttons that declare an IPX mapping using 0-based index.
   */
  async function applyFromIPX(){
    let states = null;
    try{
      const r = await fetch('/ipx/status?max_relays=32', {cache:'no-store'});
      if (r.ok){
        const j = await r.json();
        // j.relays is 1-based in payload (relay:1..N). Build 0-based boolean array.
        states = new Array(32).fill(false);
        (j.relays || []).forEach(it=>{
          const idx0 = (it.relay|0) - 1;
          if (idx0 >=0 && idx0 < states.length){
            states[idx0] = !!it.on;
          }
        });
      }
    }catch(e){/* ignore – we’ll just use text fallback */}

    document.querySelectorAll('.icon-btn').forEach(btn=>{
      const src = btn.dataset.source;
      const idx0 = Number(btn.dataset.ipxIndex);
      if (src === 'ipx' && Number.isFinite(idx0)){
        // 0-based mapping: index 0 means first relay
        const on = states ? !!states[idx0] : false;
        btn.classList.toggle('is-on', on);
      }else{
        // fallback – read any "ON/true/1" text in .js-display
        applyFromText(btn);
      }
    });
  }

  /**
   * Runs once now, and also after your own render function if it exists.
   */
  async function run(){
    await applyFromIPX();
  }

  // If you have a global render (e.g., window.loadIcons), wrap it.
  const origLoadIcons = window.loadIcons;
  if (typeof origLoadIcons === 'function'){
    window.loadIcons = async function(){
      const res = await origLoadIcons.apply(this, arguments);
      await run();
      return res;
    };
  }

  // Run on first paint as well.
  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', run, {once:true});
  }else{
    run();
  }
})();
</script>
